"""Optional: official Google Meet REST API as a transcript source.

This is the robust, terms-of-service-friendly path for meetings your own
Google Workspace organises. Instead of a browser bot, Google records and
transcribes the call for you, and after it ends you fetch the speaker-attributed
transcript entries here and feed them into the exact same summarisation pipeline
the bot uses.

It is intentionally decoupled and lazy-imported: the product runs fully without
`google-api-python-client` installed. Enable it by:

    pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

and completing an OAuth flow to obtain a token with these scopes:

    https://www.googleapis.com/auth/meetings.space.created
    https://www.googleapis.com/auth/meetings.space.readonly
    (transcripts are Google Docs, so Drive/Docs read scopes to fetch full text)

Requirements you must arrange yourself (they are account decisions, not code):
  * A Google Cloud project with the Meet REST API enabled.
  * A Workspace edition that supports meeting transcripts (Business Standard+).
  * Auto-transcription enabled on the space, or transcription turned on in-call.
  * OAuth consent from a user in the organisation that owns the meeting.

See docs/GOOGLE_MEET_API.md for the full walk-through.
"""

from __future__ import annotations

from typing import Any


class MeetApiError(RuntimeError):
    pass


def _require_libs():
    try:
        from googleapiclient.discovery import build  # noqa: F401
        from google.oauth2.credentials import Credentials  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on optional extras
        raise MeetApiError(
            "The Google API client libraries are not installed. Run: pip install "
            "google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from exc


def _meet_client(credentials: "Any"):
    from googleapiclient.discovery import build

    # Meet REST API is v2.
    return build("meet", "v2", credentials=credentials, cache_discovery=False)


def create_space(credentials: Any, access_type: str = "OPEN") -> dict[str, Any]:
    """Create a Google Meet space and return its join info.

    ``access_type`` controls the waiting room:
      * OPEN       — anyone with the link joins directly (no knocking). Best for
                     letting the recording bot in without a manual admit.
      * TRUSTED    — org users + invitees join directly; others knock.
      * RESTRICTED — only invited people can join.

    Returns ``{"name": "spaces/...", "meeting_uri": "https://meet.google.com/...",
    "meeting_code": "abc-defg-hij"}``.
    """
    _require_libs()
    client = _meet_client(credentials)

    access_type = (access_type or "OPEN").upper()
    if access_type not in ("OPEN", "TRUSTED", "RESTRICTED"):
        access_type = "OPEN"

    body = {
        "config": {
            "accessType": access_type,
            "entryPointAccess": "ALL",
        }
    }
    try:
        space = client.spaces().create(body=body).execute()
    except Exception as exc:
        raise MeetApiError(f"Could not create a Meet space: {exc}") from exc

    return {
        "name": space.get("name"),
        "meeting_uri": space.get("meetingUri"),
        "meeting_code": space.get("meetingCode"),
        "access_type": (space.get("config") or {}).get("accessType", access_type),
    }


def list_conference_records(credentials: Any, space_name: str | None = None) -> list[dict]:
    """List conference records, optionally filtered to one meeting space.

    `space_name` is the server ID like ``spaces/jQCFfuBOdN5z`` (not the code).
    """
    _require_libs()
    client = _meet_client(credentials)
    kwargs: dict[str, Any] = {}
    if space_name:
        kwargs["filter"] = f'space.name="{space_name}"'

    records: list[dict] = []
    request = client.conferenceRecords().list(**kwargs)
    while request is not None:
        response = request.execute()
        records.extend(response.get("conferenceRecords", []))
        request = client.conferenceRecords().list_next(request, response)
    return records


def fetch_transcript_entries(credentials: Any, conference_record: str) -> list[dict[str, Any]]:
    """Return speaker-attributed transcript entries for a conference record.

    ``conference_record`` looks like ``conferenceRecords/{id}``. The result is
    shaped exactly like the pipeline's caption timeline, so it can be handed
    straight to `process_meeting_audio(..., captions=...)`.
    """
    _require_libs()
    client = _meet_client(credentials)

    # 1. Find the transcript artifact(s) for this conference.
    transcripts: list[dict] = []
    request = client.conferenceRecords().transcripts().list(parent=conference_record)
    while request is not None:
        response = request.execute()
        transcripts.extend(response.get("transcripts", []))
        request = (
            client.conferenceRecords().transcripts().list_next(request, response)
        )

    if not transcripts:
        raise MeetApiError(
            "No transcript is available for this conference yet. Transcription "
            "must have been enabled, and artifacts can take a few minutes to "
            "appear after the call ends."
        )

    # 2. Resolve participant display names once, to attribute each entry.
    participant_names = _participant_names(client, conference_record)

    # 3. Pull every transcript entry, converting ms/offsets to our schema.
    timeline: list[dict[str, Any]] = []
    base_epoch: float | None = None

    for transcript in transcripts:
        name = transcript["name"]  # conferenceRecords/.../transcripts/...
        request = client.conferenceRecords().transcripts().entries().list(parent=name)
        while request is not None:
            response = request.execute()
            for entry in response.get("transcriptEntries", []):
                start = _rfc3339_to_epoch(entry.get("startTime"))
                end = _rfc3339_to_epoch(entry.get("endTime")) or start
                if start is None:
                    continue
                if base_epoch is None:
                    base_epoch = start
                speaker = participant_names.get(entry.get("participant", ""), "Speaker")
                timeline.append(
                    {
                        "startMs": int((start - base_epoch) * 1000),
                        "endMs": int(((end or start) - base_epoch) * 1000),
                        "text": (entry.get("text") or "").strip(),
                        "speaker": speaker,
                    }
                )
            request = (
                client.conferenceRecords()
                .transcripts()
                .entries()
                .list_next(request, response)
            )

    timeline.sort(key=lambda e: e["startMs"])
    return [e for e in timeline if e["text"]]


def _participant_names(client, conference_record: str) -> dict[str, str]:
    names: dict[str, str] = {}
    try:
        request = client.conferenceRecords().participants().list(parent=conference_record)
        while request is not None:
            response = request.execute()
            for participant in response.get("participants", []):
                display = (
                    (participant.get("signedinUser") or {}).get("displayName")
                    or (participant.get("anonymousUser") or {}).get("displayName")
                    or (participant.get("phoneUser") or {}).get("displayName")
                    or "Speaker"
                )
                names[participant["name"]] = display
            request = (
                client.conferenceRecords().participants().list_next(request, response)
            )
    except Exception:
        # Attribution is best-effort; entries still carry their text.
        pass
    return names


def _rfc3339_to_epoch(value: str | None) -> float | None:
    if not value:
        return None
    from datetime import datetime

    text = value.replace("Z", "+00:00")
    # Python's fromisoformat rejects >6 fractional digits; trim nanoseconds.
    if "." in text:
        head, rest = text.split(".", 1)
        frac = ""
        tz = ""
        for i, ch in enumerate(rest):
            if ch.isdigit():
                frac += ch
            else:
                tz = rest[i:]
                break
        text = f"{head}.{frac[:6]}{tz}"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def import_conference(
    credentials: Any,
    meeting_id: int,
    conference_record: str,
) -> bool:
    """Fetch a finished conference's transcript and run the summary pipeline.

    Call this once the conference has ended and its transcript artifact is
    ready. Reuses the shared pipeline, so the result is identical in shape to a
    bot-recorded meeting.
    """
    from .pipeline import process_meeting_audio

    entries = fetch_transcript_entries(credentials, conference_record)
    return process_meeting_audio(
        meeting_id,
        file_path=None,  # Google already transcribed; no local audio needed.
        captions=entries,
        participant_names={
            e["speaker"]: {"firstMs": e["startMs"], "lastMs": e["endMs"]}
            for e in entries
            if e["speaker"] and e["speaker"] != "Speaker"
        },
    )
