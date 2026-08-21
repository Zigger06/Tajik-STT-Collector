# Local API

Default base URL: `http://<PC-IP>:8000`

All `/api/v1/*` requests require:

```text
X-Project-Key: tajik-stt-local
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Server readiness |
| POST | `/api/v1/volunteers` | Register/update an anonymous volunteer |
| GET | `/api/v1/tasks/recording?volunteer_id=...` | Get one approved text to record |
| POST | `/api/v1/recordings?...` | Upload a raw `audio/wav` body |
| GET | `/api/v1/tasks/text-review?volunteer_id=...` | Get one text-review task |
| POST | `/api/v1/text-reviews` | Submit `correct`, `correction`, or `reject` |
| GET | `/api/v1/tasks/audio-review?volunteer_id=...` | Get one recording-review task |
| POST | `/api/v1/audio-reviews` | Submit `approve` or `reject` |
| GET | `/api/v1/stats` | Collection counts |
| POST | `/api/v1/admin/texts/import` | Import text items |
| GET | `/api/v1/admin/texts/needs-admin` | List proposed corrections |
| POST | `/api/v1/admin/texts/resolve` | Approve a correction or reject a text |

The backend accepts only RIFF/WAVE uploads up to 25 MB. The Android client records mono, PCM 16-bit, preferring 16 kHz with 48/44.1 kHz fallback.
