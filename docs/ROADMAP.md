# LensAi — Full Product Roadmap (step by step)

This is the end-to-end roadmap to take LensAi from its current working state to a
complete, production-grade AI meeting assistant. It is ordered so each step
builds on the previous one. Every step lists **what to do**, **how**, and a
**done-when** acceptance check.

Legend: ✅ done · 🔜 next · ⬜ planned

---

## Where we are today (baseline)

Already built and verified:

- ✅ Auth (register/login, JWT), dashboard, meeting workspace UI.
- ✅ Upload/record audio → Whisper transcription → speaker labels → Ollama summary.
- ✅ Local Playwright bot (Google Meet) as a fallback capture path.
- ✅ **Meeting BaaS hosted bot** (Google Meet / Zoom / Teams) as the primary
  capture layer — join, record, transcribe (gladia), auto-leave, summarise.
- ✅ Shared pipeline: transcript → summary/decisions/action items → Ask AI.
- ✅ Google OAuth + Google Meet REST API import path.
- ✅ Webhook receiver with signature verification; polling fallback.
- ✅ LensAi branding + bot avatar wiring.

Known constraints to carry forward: localhost can't receive webhooks (use a
tunnel), bot avatar needs a public URL, transcription needs
`transcription_enabled` + `transcription_config.provider`.

---

## Phase 0 — Stabilise the core (1–2 days) 🔜

Goal: the current single-user flow is rock-solid before adding features.

1. **Lock the capture path.**
   - Ensure every "send bot" entry point uses Meeting BaaS (`/meetings/baas`).
   - Done-when: dispatching from the UI creates `source="meetingbaas"` and a
     bot with `transcription_provider=gladia`.
2. **End-to-end smoke test with real speech.**
   - Run a real meeting, confirm transcript + summary + Ask AI populate.
   - Done-when: a spoken meeting yields non-empty transcript and summary.
3. **Config hygiene.**
   - `.env.example` complete; secrets in `.gitignore`; `/health` green.
   - Done-when: a fresh clone + `.env` boots with no missing config.
4. **Error surfacing.**
   - Show bot failure reasons and processing errors in the meeting UI.
   - Done-when: a failed bot shows a clear reason, not a spinner.

---

## Phase 1 — Calendar integration MVP (2–3 days) ⬜

Follow `docs/CALENDAR_INTEGRATION.md`. Steps:

1. **Data model**: `CalendarConnection`, `RecordingRule`, `ScheduledRecording`
   (auto-migrated on startup).
2. **Google calendar connect**: add calendar scopes to OAuth; callback exchanges
   code → refresh token → `POST /v2/calendars` (Meeting BaaS) → store uuid.
3. **List events**: `GET /integrations/calendars/{id}/events` → normalized list.
4. **Rules + auto-schedule**: `is_eligible()` + `reconcile()` calling
   `scheduleRecording`; link each to a `Meeting` row.
5. **Settings → Integrations tab**: connect button, connected list, rules,
   upcoming meetings with record/skip.
- Done-when: connecting a Google calendar auto-schedules a bot for an upcoming
  meeting and its summary appears afterward with no manual link paste.

---

## Phase 2 — Outlook + webhooks + scheduler reliability (2–3 days) ⬜

1. **Microsoft calendar**: Entra app + Graph OAuth; `calendar_platform="microsoft"`.
2. **Calendar webhooks**: `/webhooks/calendar`, reconcile on event change,
   verify signature.
3. **Periodic safety sweep**: background thread re-reconciles every N minutes.
4. **Recurrence + dedupe**: never double-schedule; handle moved/cancelled events.
- Done-when: create/move/cancel an event and the scheduled bot updates within a
  minute, for both Google and Outlook.

---

## Phase 3 — Meeting library, search & RAG (3–4 days) ⬜

1. **Folders, tags, favorites, rename**.
2. **Full-text search** across transcripts/summaries (Postgres FTS).
3. **Semantic search + Ask across meetings**: embeddings + pgvector; retrieve
   relevant chunks → Ollama (grounded answers with timestamps).
4. **Meeting page polish**: synced audio (where available), editable transcript,
   speaker rename/merge, jump-to-timestamp.
- Done-when: a user can search "what did we decide about pricing" across all
  meetings and get a cited answer.

---

## Phase 4 — Exports, sharing & notifications (2–3 days) ⬜

1. **Exports**: PDF + DOCX (summary + transcript); the markdown export already exists.
2. **Sharing**: shareable read-only meeting links with expiry + revoke.
3. **Notifications**: email/Slack when a summary is ready; per-meeting follow-ups.
- Done-when: a finished meeting can be exported and shared with one click.

---

## Phase 5 — Move to production data layer (2–3 days) ⬜

1. **PostgreSQL + pgvector** (swap SQLite `DATABASE_URL`); add Alembic migrations
   (replace the dev auto-migrator).
2. **Object storage (S3-compatible)** for any locally-stored audio/artifacts.
3. **Redis + a worker service** so bot polling/processing runs outside the API
   process (replace the in-process daemon threads).
- Done-when: the app runs with Postgres + Redis + a separate worker, multiple
  API instances behind a load balancer.

---

## Phase 6 — Multi-tenant SaaS & accounts (3–5 days) ⬜

1. **Organizations/teams**: org owns users, meetings, calendars, usage.
2. **Authorization**: every record carries org/user ownership; enforce on every
   endpoint (tenant isolation).
3. **Roles**: owner/admin/member; invite flow; email verification + password reset.
4. **Usage metering**: transcription minutes, storage, bot count per org.
- Done-when: two orgs cannot see each other's data; usage is tracked per org.

---

## Phase 7 — Billing & plans (3–4 days) ⬜

1. **Stripe integration**: Free / Pro / Business / Enterprise tiers.
2. **Plan limits**: enforce transcription-minute and meeting-length caps;
   gate advanced features (live, integrations, exports).
3. **Billing portal**: subscription management, invoices, upgrade/downgrade.
- Done-when: a user can subscribe, limits are enforced, and overage is handled.

---

## Phase 8 — Admin & observability (2–3 days) ⬜

1. **Admin dashboard**: users, orgs, meetings, failed jobs, system health.
2. **Analytics**: usage trends, transcription minutes, AI job throughput.
3. **Logging/metrics/alerts**: structured logs, error tracking, uptime alerts.
- Done-when: an admin can see failing bots and system health at a glance.

---

## Phase 9 — Security, compliance & hardening (3–4 days) ⬜

1. **HTTPS everywhere**, secure cookies, rate limiting, upload validation.
2. **Private artifact URLs**, configurable audio retention, account/meeting deletion.
3. **Audit logs**; secrets management; dependency pinning & scanning.
4. **Data handling**: consent notices for recording; region controls.
- Done-when: a security review checklist passes; deletion + retention work.

---

## Phase 10 — Deploy & scale (2–3 days) ⬜

1. **Dockerize** frontend, backend, worker; docker-compose for local prod.
2. **Deployment**: Cloudflare → Nginx → Next.js + FastAPI → Redis → workers →
   Postgres/object storage; GPU host for Whisper/Ollama if self-hosting AI.
3. **CI/CD**: build, test, migrate, deploy; health checks and rollbacks.
- Done-when: a tagged release deploys automatically and passes health checks.

---

## Suggested build order (dependencies)

```
Phase 0 ─► Phase 1 ─► Phase 2 ─► Phase 3 ─► Phase 4
   │                                   │
   └────────────► Phase 5 ─► Phase 6 ─► Phase 7 ─► Phase 8 ─► Phase 9 ─► Phase 10
```

- Do **Phase 0** immediately (stability).
- **Phases 1–2** deliver the "Integrations" feature you asked about.
- **Phase 5** (Postgres/Redis/worker) should land before heavy multi-tenant use.
- **Phases 6–7** turn it into a sellable SaaS.
- **Phases 8–10** make it operable and deployable at scale.

---

## Effort summary (rough, single developer)

| Phase | Focus | Estimate |
| --- | --- | --- |
| 0 | Stabilise core | 1–2 d |
| 1 | Calendar MVP (Google) | 2–3 d |
| 2 | Outlook + webhooks + scheduler | 2–3 d |
| 3 | Library, search, RAG | 3–4 d |
| 4 | Exports, sharing, notifications | 2–3 d |
| 5 | Postgres + Redis + worker | 2–3 d |
| 6 | Multi-tenant SaaS | 3–5 d |
| 7 | Billing & plans | 3–4 d |
| 8 | Admin & analytics | 2–3 d |
| 9 | Security & compliance | 3–4 d |
| 10 | Deploy & scale | 2–3 d |

Total: ~5–7 weeks of focused work to a production SaaS, with a usable
integrations MVP after Phase 1.

---

## Related docs

- `docs/CALENDAR_INTEGRATION.md` — detailed Phase 1–2 build blueprint.
- `docs/GOOGLE_MEET_API.md` — Google OAuth + Meet REST import path.
- `README.md` — running the app, config, and capture paths.
