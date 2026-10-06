# Google account connection + Google Meet REST API

This is the official, terms-of-service-friendly way to bring in meetings your
**Google Workspace organises**: the user connects their Google account through
a real OAuth consent screen, and the app reads their Meet conference records and
transcripts through the [Meet REST API][overview] — no browser bot.

Everything is already implemented:

| Piece | Where |
| --- | --- |
| OAuth flow (consent URL, callback, token storage/refresh, revoke) | `backend/app/ai/google_oauth.py` |
| Meet REST API (list conferences, fetch transcript entries) | `backend/app/ai/meet_api.py` |
| Endpoints (`/integrations/google/...`) | `backend/app/integrations/router.py` |
| Stored token model | `GoogleCredential` in `backend/app/models.py` |
| Connect screen + import UI | `frontend/src/app/dashboard/settings/page.tsx` |

You only need to create a Google Cloud OAuth client and paste two values into
`.env`. Steps below.

## 1. Create the OAuth client in Google Cloud

1. Go to the [Google Cloud console](https://console.cloud.google.com/) and
   create (or pick) a project.
2. **APIs & Services → Library** → enable the **Google Meet API**.
3. **APIs & Services → OAuth consent screen**:
   - User type: *External* (or *Internal* if everyone is in your Workspace).
   - Fill in app name, support email, developer email.
   - Add scopes: `.../auth/userinfo.email` and
     `.../auth/meetings.space.readonly`.
   - Add yourself as a **Test user** while the app is unverified.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**.
   - **Authorized redirect URIs** — add exactly:
     ```
     http://127.0.0.1:8000/integrations/google/callback
     ```
     (For production, add your real backend URL, which must be **https**.)
   - Create, then copy the **Client ID** and **Client secret**.

## 2. Configure the backend

In `backend/.env` (copy from `.env.example`):

```
GOOGLE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/integrations/google/callback
FRONTEND_BASE_URL=http://localhost:3000
```

Alternatively, download the client secret JSON from the console and save it as
`backend/client_secret.json` — the app picks it up automatically and you can
leave `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` blank.

Confirm it is picked up: `GET http://127.0.0.1:8000/health` →
`google.configured: true`.

The optional libraries are already installed; if you ever recreate the venv:

```powershell
backend\venv\Scripts\python -m pip install `
  google-api-python-client google-auth-oauthlib google-auth-httplib2
```

## 3. Use it

1. Run backend and frontend, sign in to the app.
2. Dashboard → **Settings** → **Connect Google account**.
3. You are sent to Google's consent screen; approve access.
4. Google redirects back to the backend callback, which stores your token and
   bounces you to **Settings** showing *Connected (your@email)*.
5. Click **List my Meet recordings**, then **Import & summarise** on any
   conference. It creates a meeting (source `meet_api`) and runs the same
   transcription-free pipeline (Google already transcribed it) → summary,
   decisions, action items, Ask AI.

## How the flow works (for maintainers)

```
Settings page ──GET /integrations/google/authorize──► backend builds consent URL
     │                                                  (state = JWT{user_id}, signed)
     └──browser redirect──► Google consent screen
                                   │  user approves
                                   ▼
        Google redirects browser to  GET /integrations/google/callback?code&state
                                   │  backend verifies state, exchanges code,
                                   │  stores token+refresh_token per user
                                   ▼
        browser redirected to  {FRONTEND_BASE_URL}/dashboard/settings?google=connected
```

- `state` is a short-lived JWT signed with the app `SECRET_KEY`, so the callback
  can attribute the token to the right user without the browser carrying the app
  session — and it can't be forged.
- Tokens are stored in `google_credentials` (one row per user). Access tokens
  refresh transparently via the stored refresh token.
- `GET /integrations/google/meet/conferences` lists conference records.
- `POST /integrations/google/meet/import {conference_record}` imports one:
  fetches speaker-attributed transcript entries and runs
  `pipeline.process_meeting_audio(..., captions=entries)` — identical output
  shape to a bot-recorded meeting.

## Scopes & limits

- Scopes requested: `openid`, `userinfo.email`, `meetings.space.readonly`.
- Transcripts require a Workspace edition that supports them (Business Standard
  or higher) with transcription enabled; artifacts appear a few minutes after a
  call ends.
- The `meetings.space.readonly` scope reads conference records and transcript
  *entries* (text + speaker + timing) directly, so no Drive scope is required.
  To also download the recording MP4 you would add Drive read scope.
- While the OAuth app is unverified, only listed **test users** can connect.

## Subscribing to "meeting ended" events (optional next step)

Instead of clicking *List*, subscribe to Meet lifecycle events via the
[Google Workspace Events API][events] and call the import path automatically
when a conference ends and its transcript is ready.

[overview]: https://developers.google.com/workspace/meet/api/guides/overview
[events]: https://developers.google.com/workspace/meet/api/guides/events
