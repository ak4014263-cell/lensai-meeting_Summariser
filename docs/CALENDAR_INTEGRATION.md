# Calendar Integration — Build From Scratch

This document is a complete blueprint for building the **Integrations** feature
(like `dashboard.meetingbaas.com/settings/integrations`): let each user connect
a Google or Microsoft calendar so the LensAi bot is **auto-scheduled** to join
and record their upcoming meetings, then summarised by the existing pipeline.

It is written so someone can build it from zero. It reuses this repo's existing
building blocks (Google OAuth, Meeting BaaS bot dispatch, the summarisation
pipeline, the webhook receiver).

---

## 1. What we're building

Per-user calendar auto-recording:

1. **Connect** a Google Workspace or Microsoft Outlook calendar via OAuth.
2. **Sync** upcoming events (with a video-meeting link) in near real-time.
3. **Rules** decide which meetings to record (all / only-organizer / only-external / only-with-link).
4. **Auto-schedule** a Meeting BaaS bot for each eligible event.
5. **Webhooks** keep scheduling in sync when events are created / moved / cancelled.
6. **Manage** connections and see upcoming meetings + their record/skip state.

We use **Meeting BaaS's Calendars API** (Option A) so we don't rebuild calendar
sync ourselves. Option B (own Google/MS calendar layer) is noted at the end.

---

## 2. Architecture

```
                    ┌────────────────────────── Frontend ──────────────────────────┐
                    │  Settings → Integrations                                       │
                    │   • Connect Google Calendar / Connect Outlook                  │
                    │   • Connected calendars list (+ disconnect)                    │
                    │   • Recording rules (toggles + default bot config)             │
                    │   • Upcoming meetings (record / skip per event)                │
                    └───────────────┬────────────────────────────────────────────────┘
                                    │ REST (JWT auth)
                    ┌───────────────▼──────────── Backend (FastAPI) ────────────────┐
                    │  /integrations/calendars/*                                     │
                    │   connect ─► get user's calendar OAuth refresh token           │
                    │            ─► POST Meeting BaaS /v2/calendars (register)        │
                    │   list events ─► GET Meeting BaaS /v2/calendars/{id}/events     │
                    │   rules engine ─► scheduleRecording for eligible events         │
                    │   /webhooks/calendar ◄── Meeting BaaS calendar events           │
                    └───────────────┬────────────────────────────────────────────────┘
                                    │ reuse
                    ┌───────────────▼───────────────────────────────────────────────┐
                    │  meetingbaas.create_bot / scheduleRecording                     │
                    │  meetingbaas_runner (poll) OR /webhooks/meetingbaas             │
                    │  pipeline.process_meeting_audio → Ollama summary                │
                    └────────────────────────────────────────────────────────────────┘
```

Key idea: a scheduled calendar recording ends up as a **Meeting row**
(`source="meetingbaas"`) exactly like a manually-dispatched bot, so the whole
downstream (status log, transcript, summary, UI) is already done.

---

## 3. Prerequisites

- A **Meeting BaaS API key** (already in `.env` as `MEETINGBAAS_API_KEY`).
- A **Google Cloud OAuth client** (already set up for this app) with the
  Calendar scope added:
  - `https://www.googleapis.com/auth/calendar.readonly`
  - `https://www.googleapis.com/auth/calendar.events.readonly`
- For Outlook: a **Microsoft Entra (Azure AD) app registration** with Microsoft
  Graph delegated scopes `Calendars.Read` and `offline_access`, and a redirect
  URI pointing at the backend callback.

Meeting BaaS registers a calendar using **your OAuth client id/secret + the
user's refresh token**, then syncs on its side.

---

## 4. Meeting BaaS Calendars API (verified shapes)

Base URL `https://api.meetingbaas.com`, header `x-meeting-baas-api-key: <key>`.

### List connected calendars
```
GET /v2/calendars
→ { "success": true, "data": [ ...calendars ], "cursor": null, "prev_cursor": null }
```

### Register (connect) a calendar
```
POST /v2/calendars
body (application/json):
{
  "calendar_platform": "google" | "microsoft",   // required
  "oauth_client_id":     "<your OAuth client id>",     // required
  "oauth_client_secret": "<your OAuth client secret>", // required
  "oauth_refresh_token": "<the USER's refresh token>", // required
  "raw_calendar_id":     "primary"                     // required (which calendar)
}
→ { "success": true, "data": { "uuid": "...", "email": "...", ... } }
```
> These required fields were confirmed against the live API's validation errors.
> `raw_calendar_id` selects which of the account's calendars to sync
> (`"primary"` for the main one).

### Get / delete a calendar
```
GET    /v2/calendars/{calendar_id}
DELETE /v2/calendars/{calendar_id}    (send a JSON body, e.g. {})
```

### List calendar events
(from the Meeting BaaS SDK — verify the exact REST path when implementing)
```
listCalendarEvents({ calendar_uuid, start_time, end_time })
→ { events: [ { id, summary, start_time, end_time, meeting_url, ... } ] }
```

### Schedule a recording bot for an event
```
scheduleRecording({
  calendar_uuid,
  event_id,
  bot_config: {
    bot_name: "LensAi Bot",
    recording_mode: "speaker_view",
    transcription_enabled: true,
    transcription_config: { provider: "gladia" }   // required with enabled
  }
})
→ { scheduled_recording: { id, ... } }
```
> Note the transcription gotcha we already hit: `transcription_enabled: true`
> MUST be paired with `transcription_config: { provider: ... }`, or the bot
> records with no transcript.

---

## 5. Data model (new tables)

```python
class CalendarConnection(Base):
    __tablename__ = "calendar_connections"
    id                = Column(Integer, primary_key=True)
    user_id           = Column(Integer, ForeignKey("users.id"), index=True)
    provider          = Column(String)   # "google" | "microsoft"
    email             = Column(String, nullable=True)
    baas_calendar_uuid= Column(String, index=True)   # Meeting BaaS calendar uuid
    raw_calendar_id   = Column(String, default="primary")
    status            = Column(String, default="active")  # active | error | revoked
    created_at        = Column(DateTime, default=datetime.utcnow)

class RecordingRule(Base):
    __tablename__ = "recording_rules"
    id            = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey("calendar_connections.id"), index=True)
    mode          = Column(String, default="only_with_link")
                    # record_all | only_organizer | only_external | only_with_link | off
    bot_name      = Column(String, default="LensAi Bot")
    recording_mode= Column(String, default="speaker_view")
    transcription_provider = Column(String, default="gladia")

class ScheduledRecording(Base):
    __tablename__ = "scheduled_recordings"
    id             = Column(Integer, primary_key=True)
    connection_id  = Column(Integer, ForeignKey("calendar_connections.id"), index=True)
    event_id       = Column(String, index=True)  # calendar event id (dedupe key)
    meeting_id     = Column(Integer, ForeignKey("meetings.id"), nullable=True)
    baas_recording_id = Column(String, nullable=True)
    starts_at      = Column(DateTime, nullable=True)
    state          = Column(String, default="scheduled")  # scheduled | skipped | recording | done | cancelled
```

`sync_schema()` (the existing auto-migrator) adds these when the app starts.

---

## 6. Backend endpoints to build

All under a new router `app/integrations/calendars.py`, JWT-protected
(`get_current_user`) except the webhook.

| Method | Path | Purpose |
| --- | --- | --- |
| GET  | `/integrations/calendars` | List the user's connected calendars + status |
| GET  | `/integrations/calendars/google/authorize` | Return Google consent URL (calendar scopes) |
| GET  | `/integrations/calendars/google/callback` | Exchange code → refresh token → register with Meeting BaaS |
| GET  | `/integrations/calendars/microsoft/authorize` | Outlook consent URL |
| GET  | `/integrations/calendars/microsoft/callback` | Exchange code → register |
| DELETE | `/integrations/calendars/{id}` | Disconnect (delete at Meeting BaaS + local) |
| GET  | `/integrations/calendars/{id}/events?from&to` | List upcoming events |
| PUT  | `/integrations/calendars/{id}/rule` | Update recording rule / default bot config |
| POST | `/integrations/calendars/{id}/events/{event_id}/record` | Manually schedule a recording |
| POST | `/integrations/calendars/{id}/events/{event_id}/skip` | Skip an event |
| POST | `/webhooks/calendar` | Meeting BaaS calendar webhook (unauthenticated + verified) |

**Connect flow (Google):** reuse the existing `google_oauth.py` pattern, but
request calendar scopes. After the callback you have the user's
`refresh_token`; POST it to Meeting BaaS `/v2/calendars` with your client
id/secret and `calendar_platform="google"`. Store the returned `uuid` in
`CalendarConnection.baas_calendar_uuid`.

---

## 7. Rules engine + scheduling

```python
def is_eligible(event, rule) -> bool:
    if rule.mode == "off":            return False
    if not event.get("meeting_url"):  return rule.mode == "record_all"
    if rule.mode == "record_all":     return True
    if rule.mode == "only_with_link": return True
    if rule.mode == "only_organizer": return event["is_organizer"]
    if rule.mode == "only_external":  return event["has_external_attendees"]
    return False

def reconcile(connection):
    events = baas.list_calendar_events(connection.baas_calendar_uuid, now, now+14d)
    for ev in events:
        already = ScheduledRecording.get(connection.id, ev.id)
        if is_eligible(ev, connection.rule) and not already:
            rec = baas.schedule_recording(connection.baas_calendar_uuid, ev.id, bot_config)
            create ScheduledRecording(state="scheduled", meeting_id=new Meeting(source="meetingbaas"))
        elif already and (ev.cancelled or not is_eligible(ev, rule)):
            baas.cancel_recording(...); already.state = "cancelled"
```

Trigger `reconcile` in two ways:
- **Webhook-driven** (preferred): on `/webhooks/calendar` event changes.
- **Periodic** safety sweep: a background thread every N minutes (reuse the
  `bot_manager`-style daemon-thread pattern).

Dedupe on `event_id` so recurring meetings don't schedule twice.

---

## 8. Webhooks

- Extend the existing verified receiver. Meeting BaaS calendar webhooks report
  event created/updated/deleted and bot lifecycle.
- Verify the signature the same way as `meetingbaas.verify_webhook`.
- On `bot.completed`, the existing `/webhooks/meetingbaas` + `finalize()` path
  already downloads the transcript and runs the summary — no extra work.

---

## 9. Frontend — Settings → Integrations tab

Add to `frontend/src/app/dashboard/settings/page.tsx` (new "Integrations" section):

- **Connect** buttons: "Connect Google Calendar", "Connect Outlook" → call
  `/authorize`, redirect to consent, handle `?calendar=connected` on return
  (mirror the existing Google-connect handling).
- **Connected calendars** list: email, provider, status, Disconnect.
- **Recording rules**: a select (Record all / Only meetings I organize / Only
  external / Only with a link / Off) + default bot name and transcription
  provider.
- **Upcoming meetings**: table of synced events with a per-row toggle
  (Record / Skip) and a badge showing scheduled state.

Add matching methods to `frontend/src/lib/api.ts`
(`listCalendars`, `connectCalendarUrl`, `disconnectCalendar`, `calendarEvents`,
`updateRule`, `recordEvent`, `skipEvent`).

---

## 10. Phased checklist

- [ ] **P1 Connect** — model `CalendarConnection`, Google calendar OAuth (add
  scopes), register with Meeting BaaS, list + disconnect, Settings UI buttons.
- [ ] **P2 Events** — `list events` endpoint + normalize + Upcoming list UI.
- [ ] **P3 Rules + schedule** — `RecordingRule`, `is_eligible`, `reconcile`,
  `scheduleRecording`, `ScheduledRecording` rows linked to `Meeting`.
- [ ] **P4 Webhooks** — `/webhooks/calendar`, reconcile on change; verify sig.
- [ ] **P5 Microsoft** — Entra app, Graph OAuth, `calendar_platform="microsoft"`.
- [ ] **P6 Reliability** — periodic sweep, token refresh, recurrence dedupe,
  per-user master "auto-record" switch, error surfacing in Settings.

---

## 11. Option B — build the calendar layer ourselves (no Meeting BaaS calendars)

If you don't want Meeting BaaS to hold the calendar connection:

- **Google**: add calendar scopes to the existing OAuth; use the Google
  Calendar API (`events.list`, `singleEvents=true`, `orderBy=startTime`); watch
  channels (`events.watch`) for push notifications.
- **Microsoft**: MSAL + Microsoft Graph (`/me/events`, `/me/calendarView`),
  Graph subscriptions for change notifications.
- Run your own scheduler thread; when an eligible event is near, call the
  existing `meetingbaas.create_bot(join_url)` (which already works) instead of
  `scheduleRecording`.
- Trade-off: full control, but you own token refresh, recurrence expansion,
  timezone handling, and change-notification renewal. ~1–2 weeks vs ~2–3 days.

---

## 12. Gotchas we already learned (apply them here)

- Transcription needs **both** `transcription_enabled: true` **and**
  `transcription_config: { provider: "gladia" }`.
- The Meeting BaaS **leave** route is `POST /v2/bots/{id}/leave` with a JSON
  body (no `DELETE`).
- On localhost, webhooks can't reach you — use a tunnel (ngrok/cloudflared) or
  rely on polling/periodic sweep.
- A bot avatar (`bot_image`) must be a **public** URL.
- Store OAuth **refresh tokens** (request `access_type=offline` + `prompt=consent`).
```
