# Collector API

Online base URL: `https://<machine>.<tailnet>.ts.net`

Volunteer endpoints exposed through Funnel do not require a password or project key. The local admin panel and `/api/v1/admin/*` remain protected with:

```text
X-Project-Key: <local-admin-key>
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Server readiness |
| POST | `/api/v1/volunteers` | Register/update an anonymous volunteer |
| POST | `/api/v1/texts` | Submit a volunteer text with an optional source for review |
| GET | `/api/v1/volunteers/stats?volunteer_id=...` | Get personal recording counts |
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

The public Funnel handler exposes only volunteer registration, recording, review, media and personal-stat endpoints. It returns 404 for the admin page, global statistics and all `/api/v1/admin/*` routes.

The backend accepts only RIFF/WAVE uploads up to 25 MB. The Android client records mono, PCM 16-bit, preferring 16 kHz with 48/44.1 kHz fallback.
