# Tajik STT Collector — Security Prelaunch Checklist

This document separates what is enforced/tested by the repository from checks that must be completed manually on the real Windows server and Android phone before public advertising.

## READY — enforced or covered by repository tests

### Android / identity

- Public release networking is HTTPS-only; debug keeps LAN/localhost HTTP for development.
- Public APK publication is configured for a permanent release keystore from GitHub Actions Secrets; signing files/passwords are not committed.
- Volunteers remain anonymous: no email, phone number, Google/Firebase account or user password.
- Each volunteer UUID is bound to a random 256-bit device credential. The PC stores only a random salt + hash, not the plaintext device secret.
- Personal volunteer API routes require the anonymous device credential.
- Device-oriented rate limits and registration proof-of-work provide practical anti-abuse/Sybil friction.

### Public / admin separation

- Online public API target and admin panel are both required by code to bind to `127.0.0.1`; Tailscale Funnel exposes only the public target on port 8000.
- `/admin`, global `/api/v1/stats`, and `/api/v1/admin/*` are hidden on the Funnel-facing handler.
- Admin key stays in the local runtime directory and is not part of Android, GitHub Pages or URLs.
- Public responses use `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and a restrictive `Permissions-Policy`.
- JSON and WAV request sizes remain bounded; malformed JSON, UUIDs and WAV data are rejected.
- File-serving paths come from fixed admin paths or validated database rows; My Data path parsing rejects nested/slashed IDs, and reviewer media also checks that the database file remains directly under the configured audio directory.
- Unexpected server exceptions are logged locally but public clients receive only `internal server error`, not filesystem paths/traceback text.

### Reviewer audio delivery

- Knowing a recording UUID alone does not authorize `/media/<recording-id>.wav`.
- An audio-review task receives a cryptographically random bearer capability tied in server memory to one recording and the reviewer to whom it was assigned.
- A new assignment invalidates older reviewer-media capabilities for that reviewer.
- Reviewer-media capability TTL is 5 minutes and the successful-download budget is 3 requests.
- The capability is invalidated immediately when that reviewer submits the review.
- Reviewer media is served only while the recording is still pending, the owner has active consent, and the assigned reviewer has not already reviewed it.
- Reviewer capability values are redacted from normal Python request logs and are never stored in SQLite/Git.
- Reviewer tasks still do not expose the recording owner's display name or volunteer UUID.

Note: reviewer capabilities are short-lived bearer URLs because Android `MediaPlayer` consumes the returned URL directly. Anyone who obtains the full capability URL during its short lifetime could use the remaining download budget. This is materially safer than permanent UUID access but is not claimed to be non-transferable hardware-bound DRM.

### My Data / deletion / consent

- `Маълумоти ман` lists only the authenticated volunteer's server recordings and allows own playback/download, ZIP download, one/all deletion and consent withdrawal.
- Deleting a server recording removes the source WAV, database recording row and dependent audio reviews and excludes it from future exports.
- Consent withdrawal blocks new contribution APIs while preserving authenticated My Data access for later download/deletion.
- Revoked recordings are excluded from future dataset exports.
- UI/Privacy Policy explicitly state that deleting source WAV cannot automatically undo training that was already completed.

### Backup tooling

- `backend/tools/backup_collector.py` uses SQLite's online backup API instead of blindly copying a live WAL database.
- The backup contains a SQLite snapshot plus exactly the WAV files referenced by that snapshot.
- Source WAV SHA-256 is checked before and after copying.
- `backup-manifest.json` records hashes; `COMPLETE` is written only after the snapshot completes.
- `backend/tools/verify_backup.py` checks the COMPLETE marker, database hash, SQLite `PRAGMA integrity_check`, recording set and every WAV hash.
- Backup scripts never delete or overwrite source recordings.
- Production backup creation refuses to proceed without explicit encrypted-destination confirmation.
- `backend/backup_to_encrypted_volume.ps1` is suitable for a manually mounted VeraCrypt volume (including Windows Home) or another encrypted volume. It requires an explicit confirmation switch and refuses to place the backup on the same mounted volume as the live data.
- `backend/backup_to_bitlocker.ps1` remains available for Windows editions where a separate BitLocker-protected backup volume can be verified by PowerShell.
- Local backup folders and common encrypted-container/image files (`.hc`, `.tc`, `.vhd`, `.vhdx`) are ignored by Git.

## MANUAL — must be completed on the real Windows server / phone

Do not call the deployment ready for public advertising until the relevant items below are checked on the actual machine.

### 1. Create and use an encrypted live-data volume

For **Windows Home**, the recommended deployment profile is a manually created **VeraCrypt standard file container**. Windows Pro/Enterprise/Education may alternatively use a BitLocker-protected VHDX.

Recommended Windows Home layout:

```text
C:\Users\<you>\Documents\GitHub\Tajik-STT-Collector\   # code only
C:\Users\<you>\TajikSTT-Secure\TajikSTT-Secure.hc    # encrypted VeraCrypt container

T:\                                                      # mounted/unlocked VeraCrypt volume
└── TajikSTT\runtime\
    ├── collector.db
    ├── online_config.json
    └── audio\
```

Create the VeraCrypt container manually:

1. `Create Volume -> Create an encrypted file container -> Standard VeraCrypt volume`.
2. Store the container outside the Git repository, for example `C:\Users\<you>\TajikSTT-Secure\TajikSTT-Secure.hc`.
3. Use a strong unique passphrase and do not put it in scripts, Git, screenshots or chat logs.
4. A normal AES-based VeraCrypt volume is sufficient; use NTFS for the mounted filesystem.
5. Mount it with a dedicated letter such as `T:` before starting Collector.
6. Do **not** enable automatic mounting/unlocking unless you deliberately accept that an unlocked Windows session can immediately access the voice data.
7. Dismount the volume when Collector is not running.
8. Keep a secure offline record of the VeraCrypt passphrase/recovery information. Losing the only unlock secret can make the dataset unrecoverable.

The repository never creates, mounts, unlocks or encrypts VeraCrypt/BitLocker volumes automatically.

### 2. Point the backend at the encrypted runtime

After mounting/unlocking the encrypted volume, create:

```text
T:\TajikSTT\runtime
T:\TajikSTT\runtime\audio
```

Before migrating existing real data, stop the Python Collector backend. **Copy, do not move first**, the existing `backend\runtime\` contents to `T:\TajikSTT\runtime\`.

Recommended verification before switching permanently:

```powershell
$src = "C:\Users\<you>\Documents\GitHub\Tajik-STT-Collector\backend\runtime"
robocopy "$src" "T:\TajikSTT\runtime" /E /COPY:DAT /DCOPY:DAT /R:1 /W:1

py -3.12 -c "import sqlite3; db=sqlite3.connect(r'T:\TajikSTT\runtime\collector.db'); print(db.execute('PRAGMA integrity_check').fetchone()[0]); db.close()"

(Get-ChildItem "$src\audio" -Filter *.wav -File -ErrorAction SilentlyContinue).Count
(Get-ChildItem "T:\TajikSTT\runtime\audio" -Filter *.wav -File -ErrorAction SilentlyContinue).Count
```

Expected: SQLite prints `ok`, the WAV counts match, and Robocopy reports no failed/mismatched files.

Temporarily test the new runtime in the current PowerShell first:

```powershell
$env:TAJIK_COLLECTOR_DATA="T:\TajikSTT\runtime"
cd C:\Users\<you>\Documents\GitHub\Tajik-STT-Collector\backend
py -3.12 server.py stats
```

If the expected statistics are present, configure the user environment variable:

```powershell
setx TAJIK_COLLECTOR_DATA "T:\TajikSTT\runtime"
```

Open a **new** terminal and verify again:

```powershell
$env:TAJIK_COLLECTOR_DATA
cd C:\Users\<you>\Documents\GitHub\Tajik-STT-Collector\backend
py -3.12 server.py stats
```

Do not delete the old unencrypted runtime until the encrypted runtime has been verified **and** a separate encrypted backup has been created and verified.

### 3. Restrict Windows access

Manually verify:

- the Windows account used to run Collector has a strong login password/PIN;
- the VeraCrypt/BitLocker live-data volume is dismounted/locked when Collector is not running;
- the Collector runtime is not in OneDrive/Dropbox/Google Drive or another automatic cloud-sync folder;
- Windows Defender/antivirus is enabled and Windows is updated;
- no unrelated Windows users have access to the mounted Collector data volume;
- do not share `T:` or the runtime folder over SMB;
- do not store the VeraCrypt password, recovery material, admin key or Android signing passwords in the repository.

If you change NTFS ACLs with `icacls`, inspect the current ACL first and keep a recovery/admin path. Do not paste destructive ACL commands blindly.

### 4. Verify the real network exposure

Start only:

```text
backend\run_online_server.bat
```

Then on Windows check:

```powershell
netstat -ano | findstr ":8000 :8001"
```

Expected for online mode: listeners should be on `127.0.0.1:8000` and `127.0.0.1:8001`, not `0.0.0.0` and not a LAN IP.

Also verify manually:

- router port forwarding for 8000/8001 is disabled;
- Windows Firewall has no unnecessary inbound Public-network rule exposing Python ports 8000/8001;
- `https://...ts.net/health` works from a phone on mobile data;
- `https://...ts.net/admin`, `.../api/v1/stats`, and `.../api/v1/admin/...` are not available through Funnel;
- `http://<PC-LAN-IP>:8001/admin` is not reachable from another device when using production online mode.

### 5. Create an encrypted backup on a DIFFERENT physical device

An encrypted live-data container stored on the server SSD does **not** protect against SSD failure.

Recommended production rule for Windows Home:

- live data: VeraCrypt container on the server SSD, mounted as `T:` only when needed;
- backup: a **different physical SSD/HDD/USB** containing a separate VeraCrypt-encrypted volume/container, mounted for example as `B:` only during backup/verification;
- keep at least two rotating verified snapshots once the dataset becomes important.

A backup VeraCrypt container must itself live on the external/different physical device. Creating a second container on the same server SSD does not satisfy the SSD-failure requirement.

After manually mounting/unlocking the encrypted backup volume as `B:`, stop the backend for the simplest operational procedure and run:

```powershell
cd C:\Users\<you>\Documents\GitHub\Tajik-STT-Collector\backend
.\backup_to_encrypted_volume.ps1 `
    -BackupRoot "B:\TajikSTT-Backups" `
    -EncryptedDestinationConfirmed
```

The generic wrapper cannot discover a VeraCrypt passphrase and does not try to. The confirmation switch means **you have already checked that `B:` is the intended mounted encrypted backup volume**. The wrapper also refuses a backup when source and destination use the same drive letter.

For a separate BitLocker-protected backup disk on a supported Windows edition, `backup_to_bitlocker.ps1` may be used instead.

Verify the newest snapshot explicitly:

```powershell
py -3.12 .\tools\verify_backup.py "B:\TajikSTT-Backups\tajik-stt-backup-YYYYMMDDTHHMMSSZ"
```

Do not consider a backup healthy until verification succeeds.

### 6. Safe restore drill

At least once before serious collection, test restore without overwriting production data:

1. Mount a separate encrypted test volume/container or create an empty directory on a mounted encrypted test volume.
2. Run `verify_backup.py` against the chosen snapshot.
3. Copy `collector.db` and `audio\` from the backup into a new test runtime directory.
4. Temporarily point only the current terminal at the restored test directory:

```powershell
$env:TAJIK_COLLECTOR_DATA="T:\TajikSTT\restore-test"
py -3.12 server.py stats
```

5. Confirm expected counts and, if appropriate, test a dataset export to a non-production output directory.
6. Close the terminal to discard the temporary environment override.

Never overwrite the only working runtime until a restore has been verified separately.

### 7. Real-phone functional/security pass

Use a test volunteer on a real Android phone and manually verify all of the following against the production-like Funnel server:

- install/update preserves the existing anonymous volunteer identity;
- with PC/server offline, recordings remain in the phone queue;
- 1–4 recordings do not upload as a partial batch;
- the fifth recording releases the complete batch and successful upload removes phone WAV copies;
- `Иловаи матн` works;
- self text-review remains blocked and another volunteer can review;
- audio review plays only the assigned item and submitting the review makes its old media URL unusable;
- `Маълумоти ман` lists only that phone's recordings;
- own WAV and ZIP download work;
- a recording UUID copied from another volunteer cannot be downloaded through My Data or raw `/media/` access;
- delete-one/delete-all really remove the source from the server view and future export;
- revoke consent stops new contribution while leaving My Data download/delete available;
- dark theme and the existing UX still behave normally.

### 8. Final signed release verification

Repository CI builds/tests release code, but before advertising verify the **actual signed APK** produced with the permanent GitHub Secrets:

1. Bump `versionCode` and `versionName` for the real release; do not overwrite an old distributed tag.
2. Run `Actions -> Publish release APK` from `main` only when all MANUAL checks above are complete.
3. Confirm the workflow's `apksigner verify` step succeeds.
4. Install that exact downloaded release APK on a clean test phone.
5. Confirm HTTPS Funnel operation and repeat the critical record/review/My Data flow once on the signed build.
6. Only then point the public website/advertising at that release.

### 9. Operational habits after launch

- Dismount the encrypted VeraCrypt/BitLocker live-data volume when the server is not in use.
- Mount/unlock `T:` **before** starting Collector; if the encrypted runtime is unavailable, do not silently fall back to collecting production data in `backend\runtime`.
- Keep Windows/Tailscale/Python/VeraCrypt updated deliberately; do not auto-upgrade major components minutes before a campaign.
- Run and verify encrypted backups on a schedule appropriate to collection volume (daily during active campaigns is a reasonable starting point).
- Periodically test a restore, not just backup creation.
- Watch server output for repeated rate-limit events or malformed traffic, but never add device secrets/reviewer tokens/admin keys to logs.
- If the admin key, VeraCrypt secret or signing material is suspected leaked, stop public collection and rotate/recover before continuing.
