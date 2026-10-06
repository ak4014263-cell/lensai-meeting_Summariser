"""Black-box smoke test of the running API on 127.0.0.1:8000.

Covers the full upload path (register -> create -> upload -> poll -> summary),
the Meet-URL validation guard, the Ask-AI endpoint and the markdown export.
The bot join itself needs a real Meet link + a human to admit it, so it is
exercised only up to the validation boundary here.
"""

from __future__ import annotations

import io
import sys
import time
import uuid
import wave

import requests

BASE = "http://127.0.0.1:8000"
SPEECH = "_verify/meeting_speech.wav"


def check(label: str, ok: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + extra) if extra else ''}")
    if not ok:
        sys.exit(1)


def main() -> None:
    email = f"smoke_{uuid.uuid4().hex[:8]}@test.local"
    password = "Passw0rd!123"

    print("1. Auth")
    r = requests.post(f"{BASE}/auth/register", json={"email": email, "password": password}, timeout=30)
    check("register", r.status_code == 200, str(r.status_code))
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    print("2. Meet URL validation guard")
    r = requests.post(f"{BASE}/meetings/bot", json={"meet_url": "not-a-link"}, headers=h, timeout=30)
    check("rejects bad link", r.status_code == 400, r.json().get("detail", ""))
    r = requests.post(f"{BASE}/meetings/bot", json={"meet_url": "https://zoom.us/j/1"}, headers=h, timeout=30)
    check("rejects zoom link", r.status_code == 400, r.json().get("detail", ""))

    print("3. Create meeting")
    r = requests.post(f"{BASE}/meetings/", json={"title": "Smoke Test Meeting"}, headers=h, timeout=30)
    check("create", r.status_code == 200)
    meeting = r.json()
    mid = meeting["id"]
    check("initial status", meeting["status"] == "created", meeting["status"])

    print("4. Upload audio")
    with open(SPEECH, "rb") as fh:
        raw = fh.read()
    # Trim the fixture to ~16s so transcription stays quick.
    buf = io.BytesIO(raw)
    with wave.open(buf, "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(min(w.getnframes(), rate * 16))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setframerate(rate)
        w.setnchannels(ch)
        w.setsampwidth(width)
        w.writeframes(frames)
    out.seek(0)

    r = requests.post(
        f"{BASE}/meetings/{mid}/audio",
        files={"file": ("clip.wav", out, "audio/wav")},
        headers=h,
        timeout=60,
    )
    check("upload accepted", r.status_code == 200, str(r.json()))

    print("5. Poll until processed (max 6 min)")
    deadline = time.time() + 360
    status = ""
    while time.time() < deadline:
        r = requests.get(f"{BASE}/meetings/{mid}", headers=h, timeout=30)
        status = r.json()["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(4)
    check("reached completed", status == "completed", status)

    meeting = requests.get(f"{BASE}/meetings/{mid}", headers=h, timeout=30).json()
    summary = meeting.get("summary") or {}
    print(f"     summary: {summary.get('executive_summary', '')[:120]}")
    print(f"     key_points={len(summary.get('key_points') or [])} "
          f"decisions={len(meeting.get('decisions') or [])} "
          f"actions={len(meeting.get('action_items') or [])}")
    check("has summary text", bool(summary.get("executive_summary")))

    print("6. Transcript")
    segs = requests.get(f"{BASE}/meetings/{mid}/transcript", headers=h, timeout=30).json()
    check("transcript populated", len(segs) > 0, f"{len(segs)} segments")
    joined = " ".join(s["text"].lower() for s in segs)
    check("transcript matches speech", any(w in joined for w in ("stripe", "payment", "gateway")), joined[:80])

    print("7. Events log")
    events = requests.get(f"{BASE}/meetings/{mid}/events", headers=h, timeout=30).json()
    check("events recorded", len(events) > 0, f"{len(events)} events")

    print("8. Ask AI")
    r = requests.post(f"{BASE}/meetings/{mid}/ask", json={"question": "What are we migrating the payment gateway to?"}, headers=h, timeout=120)
    check("ask ok", r.status_code == 200)
    answer = r.json()["answer"]
    print(f"     answer: {answer[:140]}")
    check("answer non-empty", len(answer.strip()) > 0)

    print("9. Markdown export")
    r = requests.get(f"{BASE}/meetings/{mid}/export", headers=h, timeout=30)
    check("export ok", r.status_code == 200 and "# Smoke Test Meeting" in r.text, str(r.status_code))

    print("10. Ownership isolation")
    r2 = requests.post(f"{BASE}/auth/register", json={"email": f"other_{uuid.uuid4().hex[:8]}@test.local", "password": password}, timeout=30)
    other = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    r = requests.get(f"{BASE}/meetings/{mid}", headers=other, timeout=30)
    check("other user cannot read meeting", r.status_code == 404, str(r.status_code))

    print("11. Delete")
    r = requests.delete(f"{BASE}/meetings/{mid}", headers=h, timeout=30)
    check("delete ok", r.status_code == 200)

    print("\nALL API SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
