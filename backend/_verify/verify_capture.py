"""End-to-end verification of the bot's capture path.

Exercises the real injected script against a real Chromium with a real
WebRTC peer connection, so every hop the meeting bot depends on is proven:

    Chrome fake mic (speech WAV)
      -> RTCPeerConnection loopback  (remote track, exactly like Meet)
      -> meet_capture.js RTCPeerConnection patch
      -> WebAudio mixer
      -> MediaRecorder
      -> __aiBotAudioChunk binding
      -> .webm on disk
      -> faster-whisper transcript
      -> caption timeline -> speaker labels
      -> Ollama structured report

Run from the backend directory:  python _verify\verify_capture.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app.ai.bot import CAPTURE_SCRIPT, STEALTH_SCRIPT, _browser_args  # noqa: E402
from app.config import settings  # noqa: E402

SPEECH_WAV = HERE / "meeting_speech.wav"
OUT_WEBM = HERE / "captured.webm"
RECORD_SECONDS = int(os.getenv("RECORD_SECONDS", "40"))

TEST_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>capture harness</title></head>
<body>
<h1>capture harness</h1>
<div class="a4cQT" id="captions"></div>
<script>
window.__testState = { ready: false, error: null };

// Build a caption row shaped like Google Meet's: avatar, speaker name, text.
window.__pushCaption = function (rowId, speaker, text) {
  const host = document.getElementById('captions');
  let row = document.getElementById(rowId);
  if (!row) {
    row = document.createElement('div');
    row.className = 'nMcdL';
    row.id = rowId;
    const img = document.createElement('img');
    const who = document.createElement('div');
    who.className = 'who';
    const wrap = document.createElement('div');
    const body = document.createElement('div');
    body.className = 'body';
    wrap.appendChild(body);
    row.appendChild(img);
    row.appendChild(who);
    row.appendChild(wrap);
    host.appendChild(row);
  }
  row.querySelector('.who').textContent = speaker;
  row.querySelector('.body').textContent = text;
};

window.__dropCaption = function (rowId) {
  const row = document.getElementById(rowId);
  if (row) row.remove();
};

// A local WebRTC loopback. pc2 receives the fake microphone as a *remote*
// track, which is precisely the shape meet_capture.js hooks in a real call.
(async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const pc1 = new RTCPeerConnection();
    const pc2 = new RTCPeerConnection();
    pc1.onicecandidate = (e) => e.candidate && pc2.addIceCandidate(e.candidate);
    pc2.onicecandidate = (e) => e.candidate && pc1.addIceCandidate(e.candidate);
    pc2.ontrack = () => { window.__testState.sawTrack = true; };
    stream.getAudioTracks().forEach((t) => pc1.addTrack(t, stream));
    const offer = await pc1.createOffer();
    await pc1.setLocalDescription(offer);
    await pc2.setRemoteDescription(offer);
    const answer = await pc2.createAnswer();
    await pc2.setLocalDescription(answer);
    await pc1.setRemoteDescription(answer);
    window.__testState.ready = true;
  } catch (e) {
    window.__testState.error = String(e);
  }
})();
</script>
</body></html>
"""


def fail(message: str) -> None:
    print(f"\n[FAIL] {message}")
    sys.exit(1)


async def capture() -> dict:
    from playwright.async_api import async_playwright

    if not SPEECH_WAV.exists():
        fail(f"missing speech fixture {SPEECH_WAV} (run make_speech.ps1 first)")

    if OUT_WEBM.exists():
        OUT_WEBM.unlink()

    received = {"bytes": 0, "chunks": 0}
    sink = open(OUT_WEBM, "wb")

    args = [a for a in _browser_args() if not a.startswith("--use-file-for-fake-audio-capture")]
    args.append(f"--use-file-for-fake-audio-capture={SPEECH_WAV}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=args)
        context = await browser.new_context(
            permissions=["microphone", "camera"],
            viewport={"width": 1280, "height": 820},
        )

        async def on_chunk(source, b64):  # noqa: ARG001
            data = base64.b64decode(b64)
            sink.write(data)
            sink.flush()
            received["bytes"] += len(data)
            received["chunks"] += 1

        await context.expose_binding("__aiBotAudioChunk", on_chunk)
        await context.add_init_script(STEALTH_SCRIPT)
        await context.add_init_script(CAPTURE_SCRIPT)

        page = await context.new_page()
        await page.route(
            "https://harness.test/**",
            lambda route: asyncio.ensure_future(
                route.fulfill(status=200, content_type="text/html", body=TEST_PAGE)
            ),
        )
        await page.goto("https://harness.test/index.html", wait_until="load")

        # Wait for the loopback to negotiate.
        for _ in range(40):
            state = await page.evaluate("() => window.__testState")
            if state.get("error"):
                fail(f"harness page error: {state['error']}")
            if state.get("ready"):
                break
            await asyncio.sleep(0.25)
        else:
            fail("WebRTC loopback never became ready")

        await page.evaluate("() => window.__aiBotStartCaptions()")
        start = await page.evaluate(
            "([ms, br]) => window.__aiBotStartRecording(ms, br)",
            [settings.BOT_AUDIO_CHUNK_MS, settings.BOT_AUDIO_BITRATE],
        )
        print(f"[harness] startRecording -> {start}")
        if not start.get("ok"):
            fail(f"recorder refused to start: {start}")

        # Drive caption rows the way Meet does: text grows in place, then the
        # row is replaced by the next utterance.
        script_lines = [
            ("Priya", "We agreed to move the payment gateway to Stripe"),
            ("Priya", "We agreed to move the payment gateway to Stripe by the end of this quarter"),
            ("Rahul", "I will fix the login bug and deploy the patch on Wednesday"),
            ("Ajay", "There is a risk that the load testing environment is not ready in time"),
        ]
        elapsed = 0
        for index, (speaker, text) in enumerate(script_lines):
            row = f"row{index // 2}"
            await page.evaluate(
                "([r,s,t]) => window.__pushCaption(r,s,t)", [row, speaker, text]
            )
            await asyncio.sleep(3)
            elapsed += 3
            if index % 2 == 1:
                await page.evaluate("(r) => window.__dropCaption(r)", row)

        remaining = max(0, RECORD_SECONDS - elapsed)
        print(f"[harness] recording for another {remaining}s...")
        for _ in range(remaining):
            await asyncio.sleep(1)

        status = await page.evaluate("() => window.__aiBotStatus()")
        captions = await page.evaluate("() => window.__aiBotAllCaptions()")
        names = await page.evaluate("() => window.__aiBotNames()")
        stop = await page.evaluate("() => window.__aiBotStopRecording()")
        await asyncio.sleep(1.5)

        await context.close()
        await browser.close()

    sink.close()
    return {
        "received": received,
        "status": status,
        "captions": captions,
        "names": names,
        "stop": stop,
    }


def main() -> None:
    print("=" * 72)
    print("1. Browser capture")
    print("=" * 72)
    result = asyncio.run(capture())

    status = result["status"]
    received = result["received"]
    print(f"  remote audio tracks intercepted : {status['remoteAudioTracks']}")
    print(f"  audio context state             : {status['audioContextState']}")
    print(f"  peak signal level (RMS)         : {status['audioLevelPeak']:.5f}")
    print(f"  chunks -> python                : {received['chunks']}")
    print(f"  bytes  -> python                : {received['bytes']:,}")
    print(f"  caption entries                 : {len(result['captions'])}")
    print(f"  speakers seen                   : {list(result['names'].keys())}")
    if status.get("errors"):
        print(f"  in-page notes                   : {status['errors']}")

    if status["remoteAudioTracks"] < 1:
        fail("no remote audio track was intercepted")
    if received["bytes"] < 10_000:
        fail(f"barely any audio reached python ({received['bytes']} bytes)")
    if status["audioLevelPeak"] < 1e-3:
        fail("captured audio is silent")
    if not result["captions"]:
        fail("no captions were scraped")

    print("\n" + "=" * 72)
    print("2. Decode the recording")
    print("=" * 72)
    import av
    import numpy as np

    with av.open(str(OUT_WEBM)) as container:
        stream = container.streams.audio[0]
        samples = []
        for frame in container.decode(stream):
            samples.append(frame.to_ndarray().ravel())
        audio = np.concatenate(samples) if samples else np.array([])
    duration = len(audio) / (stream.rate or 48000)
    rms = float(np.sqrt(np.mean(audio.astype("float64") ** 2))) if audio.size else 0.0
    print(f"  file size    : {OUT_WEBM.stat().st_size:,} bytes")
    print(f"  codec        : {stream.codec_context.name} @ {stream.rate} Hz")
    print(f"  duration     : {duration:.1f}s")
    print(f"  overall RMS  : {rms:.5f}")
    if duration < 10:
        fail(f"recording is too short ({duration:.1f}s)")
    if rms <= 0:
        fail("decoded audio is pure silence")

    print("\n" + "=" * 72)
    print("3. Whisper transcription")
    print("=" * 72)
    from app.ai.transcription import transcribe_file

    stt = transcribe_file(str(OUT_WEBM))
    segments = stt["segments"]
    print(f"  segments : {len(segments)}  language: {stt['language']}")
    for seg in segments[:6]:
        print(f"   [{seg['start_ms']/1000:6.1f}s] {seg['text'][:88]}")
    if not segments:
        fail("whisper produced no segments from the captured audio")

    text = " ".join(s["text"].lower() for s in segments)
    expected = ["stripe", "login", "payment", "friday"]
    hits = [w for w in expected if w in text]
    print(f"  expected keywords found : {hits}")
    if len(hits) < 2:
        fail(f"transcript does not match the spoken script (found {hits})")

    print("\n" + "=" * 72)
    print("4. Speaker attribution from captions")
    print("=" * 72)
    from app.ai.pipeline import build_transcript_text, clean_captions, label_speakers

    timeline = clean_captions(result["captions"])
    print(f"  caption timeline entries : {len(timeline)}")
    for entry in timeline:
        print(f"   [{entry['start_ms']:>6}ms] {entry['speaker']}: {entry['text'][:70]}")

    # The harness recycles one caption row across two different speakers, which
    # is what Meet does. Each speaker must end up in their own entry.
    caption_speakers = {e["speaker"] for e in timeline}
    print(f"  distinct caption speakers : {sorted(s for s in caption_speakers if s)}")
    for expected_speaker in ("Priya", "Rahul", "Ajay"):
        if expected_speaker not in caption_speakers:
            fail(
                f"caption speaker '{expected_speaker}' was lost — a recycled row "
                "merged two speakers into one entry"
            )
    for entry in timeline:
        if "login bug" in entry["text"] and "load testing" in entry["text"]:
            fail("two speakers' words were merged into a single caption entry")
    label_speakers(segments, timeline)
    labelled = sum(1 for s in segments if s.get("speaker") and s["speaker"] != "Speaker")
    print(f"  segments given a real speaker name : {labelled}/{len(segments)}")
    if labelled == 0:
        fail("speaker labelling assigned no names at all")

    transcript_text = build_transcript_text(segments)
    print("\n  transcript preview:")
    for line in transcript_text.splitlines()[:6]:
        print(f"   {line[:100]}")

    print("\n" + "=" * 72)
    print("5. Ollama meeting report")
    print("=" * 72)
    from app.ai.ollama_service import check_available, generate_meeting_insights

    ok, detail = check_available()
    print(f"  ollama : {detail}")
    if not ok:
        fail(detail)

    insights = generate_meeting_insights(transcript_text)
    print(json.dumps(insights, indent=2, ensure_ascii=False)[:2600])

    if not insights.get("executive_summary"):
        fail("no executive summary was produced")
    populated = [
        key
        for key in ("key_points", "decisions", "action_items", "topics", "risks", "questions")
        if insights.get(key)
    ]
    print(f"\n  populated sections : {populated}")
    if len(populated) < 3:
        fail(f"report is too thin (only {populated})")

    print("\n" + "=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)


if __name__ == "__main__":
    main()
