/*
 * meet_capture.js — injected into the Google Meet page before any page script
 * runs (Playwright `add_init_script`).
 *
 * Responsibilities
 * ----------------
 * 1. AUDIO. Patch `RTCPeerConnection` so every inbound remote audio track is
 *    intercepted, mixed through a single WebAudio graph, and recorded by one
 *    `MediaRecorder`. Encoded chunks are handed to Python via the exposed
 *    binding `__aiBotAudioChunk`, which appends them to a .webm file. Only
 *    *remote* tracks are tapped, so the bot's own (fake) microphone never
 *    contaminates the recording.
 *
 *    A second, optional tap on the same graph (`__aiBotStartPcmTap`) emits raw
 *    16-bit mono PCM through `__aiBotPcmChunk` for live, in-meeting
 *    transcription. The two are independent: the file capture remains the
 *    authoritative source for the post-meeting transcript.
 *
 * 2. CAPTIONS. Poll Meet's live-caption rows to build a speaker-attributed
 *    timeline. Whisper produces the accurate text; these captions supply the
 *    speaker names that Whisper alone cannot know.
 *
 * 3. PRESENCE. Expose a participant count, in-call detection and call-ended
 *    detection so the bot knows when every human has left.
 *
 * Everything is wrapped in try/catch: if Google reshuffles their DOM the worst
 * case is degraded metadata, never a crashed bot.
 */

(() => {
  "use strict";

  if (window.__aiBotInstalled) return;
  window.__aiBotInstalled = true;

  // ───────────────────────────── state ──────────────────────────────────
  const S = {
    recStartedAt: null,
    recStoppedAt: null,
    recording: false,
    bytesSent: 0,
    chunksSent: 0,
    audioGraphReady: false,
    remoteTracks: new Set(),
    liveRemoteTracks: 0,
    peerConnections: [],
    audioLevelPeak: 0,
    audioLevelRecent: 0,
    captions: [], // { id, speaker, text, startMs, endMs, done }
    captionSeq: 0,
    namesSeen: {}, // name -> { firstMs, lastMs }
    errors: [],
    stopRequested: false,
    // Live PCM tap (independent of the MediaRecorder file capture).
    pcmTapActive: false,
    pcmSampleRate: 0,
    pcmSamplesSent: 0,
    pcmChunksSent: 0,
  };
  window.__aiBot = S;

  const now = () => Date.now();
  const relMs = () => (S.recStartedAt ? now() - S.recStartedAt : 0);
  const note = (msg) => {
    S.errors.push(String(msg).slice(0, 300));
    if (S.errors.length > 50) S.errors.shift();
  };

  // ══════════════════════════ 1. AUDIO CAPTURE ══════════════════════════

  let ac = null;
  let mixer = null; // MediaStreamAudioDestinationNode -> what we record
  let silentSink = null; // keeps the graph pulling even with muted output
  let analyser = null;
  let analyserBuf = null;
  const sourceRefs = []; // hold references so nodes are not garbage collected

  function ensureAudioGraph() {
    if (ac) return true;
    try {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) return false;
      ac = new Ctor({ sampleRate: 48000 });
      mixer = ac.createMediaStreamDestination();
      // Speech is mono. Downmixing halves the recording size and the time
      // Whisper spends decoding it.
      try {
        mixer.channelCount = 1;
        mixer.channelCountMode = "explicit";
        mixer.channelInterpretation = "speakers";
      } catch (e) {
        /* stereo is fine, just larger */
      }

      // A zero-gain path to the hardware sink. Without a consumer Chrome can
      // idle the graph, which would produce a silent recording.
      silentSink = ac.createGain();
      silentSink.gain.value = 0;
      silentSink.connect(ac.destination);

      analyser = ac.createAnalyser();
      analyser.fftSize = 1024;
      analyserBuf = new Float32Array(analyser.fftSize);

      S.audioGraphReady = true;
      resumeAudio();
      return true;
    } catch (e) {
      note("audio graph: " + e);
      return false;
    }
  }

  function resumeAudio() {
    try {
      if (ac && ac.state !== "running") ac.resume().catch(() => {});
    } catch (e) {
      /* ignore */
    }
  }

  function addRemoteAudioTrack(track) {
    try {
      if (!track || track.kind !== "audio") return;
      if (S.remoteTracks.has(track)) return;
      if (!ensureAudioGraph()) return;

      S.remoteTracks.add(track);
      const stream = new MediaStream([track]);

      // Chrome will not deliver samples from a remote track that has no media
      // sink attached, even when it is routed into WebAudio. A muted <audio>
      // element is the long-standing workaround.
      const el = document.createElement("audio");
      el.srcObject = stream;
      el.autoplay = true;
      el.muted = true;
      el.setAttribute("data-ai-bot-sink", "1");
      el.style.display = "none";
      document.body && document.body.appendChild(el);
      el.play().catch(() => {});

      const src = ac.createMediaStreamSource(stream);
      src.connect(mixer);
      src.connect(silentSink);
      if (analyser) src.connect(analyser);

      sourceRefs.push({ src, el, track });
      S.liveRemoteTracks = countLiveTracks();

      const drop = () => {
        S.liveRemoteTracks = countLiveTracks();
      };
      track.addEventListener("ended", drop);
      track.addEventListener("mute", drop);
      track.addEventListener("unmute", drop);
      resumeAudio();
    } catch (e) {
      note("addRemoteAudioTrack: " + e);
    }
  }

  function countLiveTracks() {
    let n = 0;
    S.remoteTracks.forEach((t) => {
      if (t.readyState === "live") n++;
    });
    return n;
  }

  // Patch RTCPeerConnection. The constructor returns a genuine native
  // instance, so `instanceof` and internal Meet plumbing keep working.
  try {
    const Native = window.RTCPeerConnection || window.webkitRTCPeerConnection;
    if (Native && !Native.__aiPatched) {
      const Patched = function (...args) {
        const pc = new Native(...args);
        try {
          S.peerConnections.push(pc);
          pc.addEventListener("track", (ev) => {
            try {
              if (ev.track && ev.track.kind === "audio") {
                addRemoteAudioTrack(ev.track);
              }
            } catch (e) {
              note("ontrack: " + e);
            }
          });
        } catch (e) {
          note("pc patch: " + e);
        }
        return pc;
      };
      Patched.prototype = Native.prototype;
      Object.setPrototypeOf(Patched, Native);
      Patched.__aiPatched = true;
      window.RTCPeerConnection = Patched;
      window.webkitRTCPeerConnection = Patched;
    }
  } catch (e) {
    note("rtc patch: " + e);
  }

  // Some clients hand remote streams straight to a media element instead of
  // firing `track`. Catch those too by watching srcObject assignments.
  try {
    const proto = HTMLMediaElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "srcObject");
    if (desc && desc.set && !proto.__aiSrcObjectPatched) {
      Object.defineProperty(proto, "srcObject", {
        configurable: true,
        enumerable: desc.enumerable,
        get: desc.get,
        set: function (stream) {
          try {
            if (
              stream &&
              typeof stream.getAudioTracks === "function" &&
              !this.hasAttribute("data-ai-bot-sink")
            ) {
              stream.getAudioTracks().forEach((t) => {
                // Local mic tracks are not interesting; only remote ones.
                if (t.label && /microphone|default/i.test(t.label)) return;
                addRemoteAudioTrack(t);
              });
            }
          } catch (e) {
            note("srcObject: " + e);
          }
          return desc.set.call(this, stream);
        },
      });
      proto.__aiSrcObjectPatched = true;
    }
  } catch (e) {
    note("srcObject patch: " + e);
  }

  let recorder = null;

  function sampleLevel() {
    try {
      if (!analyser || !analyserBuf) return;
      analyser.getFloatTimeDomainData(analyserBuf);
      let sum = 0;
      for (let i = 0; i < analyserBuf.length; i++) {
        sum += analyserBuf[i] * analyserBuf[i];
      }
      const rms = Math.sqrt(sum / analyserBuf.length);
      S.audioLevelRecent = rms;
      if (rms > S.audioLevelPeak) S.audioLevelPeak = rms;
    } catch (e) {
      /* ignore */
    }
  }

  window.__aiBotStartRecording = function (timesliceMs, bitrate) {
    try {
      if (S.recording) return { ok: true, already: true };
      if (!ensureAudioGraph()) return { ok: false, error: "no audio graph" };
      resumeAudio();

      const candidates = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/ogg;codecs=opus",
      ];
      const mimeType = candidates.find(
        (m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)
      );
      if (!mimeType) return { ok: false, error: "no supported mime type" };

      recorder = new MediaRecorder(mixer.stream, {
        mimeType,
        audioBitsPerSecond: bitrate || 96000,
      });

      recorder.ondataavailable = async (ev) => {
        try {
          if (!ev.data || ev.data.size === 0) return;
          const buf = await ev.data.arrayBuffer();
          const bytes = new Uint8Array(buf);
          let bin = "";
          const CH = 0x8000;
          for (let i = 0; i < bytes.length; i += CH) {
            bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
          }
          S.bytesSent += bytes.length;
          S.chunksSent += 1;
          if (typeof window.__aiBotAudioChunk === "function") {
            await window.__aiBotAudioChunk(btoa(bin));
          }
        } catch (e) {
          note("ondataavailable: " + e);
        }
      };
      recorder.onerror = (e) => note("recorder error: " + (e && e.error));

      recorder.start(timesliceMs || 4000);
      S.recStartedAt = now();
      S.recording = true;
      setInterval(sampleLevel, 500);
      return { ok: true, mimeType };
    } catch (e) {
      note("startRecording: " + e);
      return { ok: false, error: String(e) };
    }
  };

  // ─────────────────── live PCM tap (real-time transcription) ────────────
  //
  // The MediaRecorder path above produces WebM/Opus, which is what gets written
  // to disk for the authoritative post-meeting transcript. Live transcription
  // needs something Whisper can consume immediately without a container parse,
  // so this taps the same mixed graph and emits raw 16-bit mono PCM at the
  // sample rate the server asks for.
  //
  // Samples are buffered to roughly half a second before crossing into Python:
  // the ScriptProcessor fires every ~85 ms at 48 kHz, and one binding call per
  // callback would be needlessly chatty.

  let pcmSource = null;
  let pcmNode = null;
  let pcmSink = null;
  let pcmTargetRate = 16000;
  let pcmPending = [];
  let pcmPendingLength = 0;
  let pcmFlushThreshold = 8000;

  function pcmFlush() {
    if (!pcmPendingLength) return;
    try {
      const merged = new Int16Array(pcmPendingLength);
      let at = 0;
      for (const part of pcmPending) {
        merged.set(part, at);
        at += part.length;
      }
      pcmPending = [];
      pcmPendingLength = 0;

      const bytes = new Uint8Array(
        merged.buffer,
        merged.byteOffset,
        merged.byteLength
      );
      let bin = "";
      const CH = 0x8000;
      for (let i = 0; i < bytes.length; i += CH) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
      }

      S.pcmSamplesSent += merged.length;
      S.pcmChunksSent += 1;

      if (typeof window.__aiBotPcmChunk === "function") {
        // Deliberately not awaited: this runs inside onaudioprocess, and
        // blocking the audio callback would drop samples.
        const p = window.__aiBotPcmChunk(btoa(bin));
        if (p && typeof p.catch === "function") p.catch(() => {});
      }
    } catch (e) {
      note("pcmFlush: " + e);
    }
  }

  window.__aiBotStartPcmTap = function (targetRate, bufferSize) {
    try {
      if (S.pcmTapActive) return { ok: true, already: true };
      if (!ensureAudioGraph()) return { ok: false, error: "no audio graph" };
      resumeAudio();

      pcmTargetRate = targetRate || 16000;
      // Flush about twice a second.
      pcmFlushThreshold = Math.max(1024, Math.floor(pcmTargetRate / 2));

      const size = bufferSize || 4096;
      const factory = ac.createScriptProcessor || ac.createJavaScriptNode;
      if (!factory) return { ok: false, error: "no ScriptProcessor support" };

      // Read the mixed output rather than each source, so the tap sees exactly
      // what the recording does.
      pcmSource = ac.createMediaStreamSource(mixer.stream);
      pcmNode = factory.call(ac, size, 1, 1);

      pcmNode.onaudioprocess = function (ev) {
        try {
          if (!S.pcmTapActive) return;
          const input = ev.inputBuffer.getChannelData(0);
          const ratio = ac.sampleRate / pcmTargetRate;

          if (ratio <= 1.0001) {
            // Already at or below the target rate: pass through.
            const out = new Int16Array(input.length);
            for (let i = 0; i < input.length; i++) {
              const s = Math.max(-1, Math.min(1, input[i]));
              out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
            }
            pcmPending.push(out);
            pcmPendingLength += out.length;
          } else {
            // Decimate with box averaging, which doubles as a cheap
            // anti-aliasing filter. 48 kHz -> 16 kHz is an exact 3:1.
            const outLen = Math.floor(input.length / ratio);
            const out = new Int16Array(outLen);
            for (let i = 0; i < outLen; i++) {
              const from = Math.floor(i * ratio);
              const to = Math.min(input.length, Math.floor((i + 1) * ratio));
              let sum = 0;
              let n = 0;
              for (let j = from; j < to; j++) {
                sum += input[j];
                n++;
              }
              let s = n ? sum / n : 0;
              s = Math.max(-1, Math.min(1, s));
              out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
            }
            pcmPending.push(out);
            pcmPendingLength += out.length;
          }

          if (pcmPendingLength >= pcmFlushThreshold) pcmFlush();
        } catch (e) {
          note("pcmTap: " + e);
        }
      };

      // A ScriptProcessor only runs while connected to a destination.
      pcmSink = ac.createGain();
      pcmSink.gain.value = 0;
      pcmSource.connect(pcmNode);
      pcmNode.connect(pcmSink);
      pcmSink.connect(ac.destination);

      S.pcmTapActive = true;
      S.pcmSampleRate = pcmTargetRate;
      return {
        ok: true,
        rate: pcmTargetRate,
        contextRate: ac.sampleRate,
        bufferSize: size,
      };
    } catch (e) {
      note("startPcmTap: " + e);
      return { ok: false, error: String(e) };
    }
  };

  window.__aiBotStopPcmTap = function () {
    try {
      if (!S.pcmTapActive) {
        return { ok: true, already: true, samples: S.pcmSamplesSent };
      }
      pcmFlush();
      S.pcmTapActive = false;
      for (const node of [pcmSource, pcmNode, pcmSink]) {
        try {
          node && node.disconnect();
        } catch (e) {
          /* ignore */
        }
      }
      if (pcmNode) pcmNode.onaudioprocess = null;
      pcmSource = null;
      pcmNode = null;
      pcmSink = null;
      return {
        ok: true,
        samples: S.pcmSamplesSent,
        chunks: S.pcmChunksSent,
      };
    } catch (e) {
      note("stopPcmTap: " + e);
      S.pcmTapActive = false;
      return { ok: false, error: String(e) };
    }
  };

  window.__aiBotStopRecording = function () {
    return new Promise((resolve) => {
      try {
        S.stopRequested = true;
        if (!recorder || !S.recording) {
          S.recording = false;
          return resolve({ ok: true, already: true, bytes: S.bytesSent });
        }
        const done = () => {
          S.recording = false;
          S.recStoppedAt = now();
          resolve({ ok: true, bytes: S.bytesSent, chunks: S.chunksSent });
        };
        recorder.onstop = done;
        // requestData() flushes whatever is buffered before the final stop.
        try {
          recorder.requestData();
        } catch (e) {
          /* not fatal */
        }
        recorder.stop();
        setTimeout(done, 4000); // hard fallback if onstop never fires
      } catch (e) {
        note("stopRecording: " + e);
        S.recording = false;
        resolve({ ok: false, error: String(e), bytes: S.bytesSent });
      }
    });
  };

  // ═══════════════════════════ 2. CAPTIONS ══════════════════════════════

  const CAPTION_NOISE = [
    /^captions?$/i,
    /^turn on captions?$/i,
    /^jump to bottom$/i,
    /^(english|hindi|spanish|french|german)\b.*\(.*\)$/i,
    /^more options$/i,
    /^you$/i,
    // Language selection UI
    /^language$/i,
    /\bBETA\b/i,
    /(afrikaans|albanian|amharic|arabic|armenian|azerbaijani|basque|bengali|bulgarian|burmese|catalan|chinese|czech|dutch|estonian|filipino|finnish|galician|georgian|greek|gujarati|hebrew|hungarian|icelandic|indonesian|italian|javanese|kannada|kazakh|khmer|korean|lao|latvian|lithuanian|macedonian|malay|malayalam|marathi|mongolian|nepali|norwegian|persian|polish|portuguese|romanian|russian|serbian|sinhala|slovak|slovenian|sundanese|swahili|swedish|tamil|telugu|thai|turkish|ukrainian|urdu|uzbek|vietnamese|xhosa|zulu|tswana|sesotho)/i,
    // Font/formatting UI
    /format_size|font size/i,
    /(tiny|small|medium|large|huge|jumbo)\s*$/i,
    /font colour|circle/i,
    /(default|white|black|blue|green|red|yellow|cyan|magenta)\s*$/i,
    /open caption settings/i,
    /^settings$/i,
  ];

  function isNoise(text) {
    if (!text) return true;
    const t = text.trim();
    if (t.length < 2) return true;
    return CAPTION_NOISE.some((re) => re.test(t));
  }

  function leafTexts(root) {
    const out = [];
    try {
      const walk = root.querySelectorAll("*");
      for (const el of walk) {
        if (el.children.length !== 0) continue;
        if (el.tagName === "IMG" || el.tagName === "SVG") continue;
        const t = (el.innerText || el.textContent || "").trim();
        if (t) out.push(t);
      }
      if (out.length === 0) {
        const t = (root.innerText || root.textContent || "").trim();
        if (t) out.push(t);
      }
    } catch (e) {
      /* ignore */
    }
    return out;
  }

  function findCaptionRows() {
    // Known-stable-ish hooks first, then a structural fallback.
    const rowSelectors = ["div.nMcdL", "div[class*='nMcdL']"];
    for (const sel of rowSelectors) {
      try {
        const found = document.querySelectorAll(sel);
        if (found.length) return Array.from(found);
      } catch (e) {
        /* ignore */
      }
    }

    const containerSelectors = [
      'div[jsname="dsyhDe"]',
      "div.a4cQT",
      '[role="region"][aria-label*="aption" i]',
      'div[aria-live="polite"]',
    ];
    const seen = new Set();
    let best = null;
    let bestScore = 0;
    for (const sel of containerSelectors) {
      let nodes = [];
      try {
        nodes = Array.from(document.querySelectorAll(sel));
      } catch (e) {
        continue;
      }
      for (const node of nodes) {
        if (seen.has(node)) continue;
        seen.add(node);
        const kids = Array.from(node.children).filter((c) => {
          const t = (c.innerText || "").trim();
          return t.length > 1;
        });
        // Prefer containers that look like a short stack of caption lines.
        const score = kids.length > 0 && kids.length <= 12 ? kids.length : 0;
        if (score > bestScore) {
          bestScore = score;
          best = kids;
        }
      }
    }
    return best || [];
  }

  function parseRow(row) {
    const leaves = leafTexts(row);
    if (leaves.length === 0) return null;

    let speaker = null;
    let textParts = leaves;

    // Meet renders the speaker name as the first short leaf of the row.
    if (leaves.length >= 2 && leaves[0].length <= 60 && !/[.!?]$/.test(leaves[0])) {
      speaker = leaves[0];
      textParts = leaves.slice(1);
    }

    const text = textParts.join(" ").replace(/\s+/g, " ").trim();
    if (isNoise(text)) return null;
    if (speaker) {
      speaker = speaker.replace(/\s+/g, " ").trim();
    }
    return { speaker: speaker || null, text };
  }

  /* Meet mutates a caption row in place while someone speaks, and once the
   * utterance is long it drops words off the front. Stitch old and new text
   * back together via the largest suffix/prefix overlap. */
  function mergeGrowingText(prev, next) {
    if (!prev) return next;
    if (!next) return prev;
    if (next.startsWith(prev)) return next;
    if (prev.endsWith(next)) return prev;
    if (prev.includes(next)) return prev;
    const max = Math.min(prev.length, next.length);
    for (let len = max; len >= 12; len--) {
      if (prev.slice(prev.length - len) === next.slice(0, len)) {
        return prev + next.slice(len);
      }
    }
    return prev + " " + next;
  }

  const rowIndex = new WeakMap(); // row element -> caption id

  function pollCaptions() {
    let rows;
    try {
      rows = findCaptionRows();
    } catch (e) {
      return;
    }

    const active = new Set();

    for (const row of rows) {
      let parsed;
      try {
        parsed = parseRow(row);
      } catch (e) {
        continue;
      }
      if (!parsed) continue;

      const t = relMs();
      const id = rowIndex.get(row);
      let entry = id != null ? S.captions.find((c) => c.id === id) : null;

      // Meet recycles a caption row for the next speaker. Treating that as a
      // continuation would merge two people's words into one attributed line,
      // so close the old entry and start a fresh one.
      if (entry && parsed.speaker && entry.speaker && parsed.speaker !== entry.speaker) {
        entry.done = true;
        rowIndex.delete(row);
        entry = null;
      }

      if (!entry) {
        // Meet sometimes swaps the DOM node for an ongoing utterance. Reuse
        // the most recent open entry from the same speaker when the text is
        // clearly a continuation.
        const open = S.captions
          .slice(-4)
          .reverse()
          .find(
            (c) =>
              !c.done &&
              c.speaker === parsed.speaker &&
              (parsed.text.startsWith(c.text.slice(0, 24)) ||
                c.text.startsWith(parsed.text.slice(0, 24)))
          );
        if (open) {
          entry = open;
        } else {
          entry = {
            id: ++S.captionSeq,
            speaker: parsed.speaker,
            text: parsed.text,
            startMs: t,
            endMs: t,
            done: false,
            rev: 0,
          };
          S.captions.push(entry);
        }
        rowIndex.set(row, entry.id);
      }

      const merged = mergeGrowingText(entry.text, parsed.text);
      if (merged !== entry.text) {
        entry.text = merged;
        entry.rev++;
      }
      entry.endMs = t;
      if (parsed.speaker && !entry.speaker) entry.speaker = parsed.speaker;
      active.add(entry.id);

      if (parsed.speaker) {
        const rec = S.namesSeen[parsed.speaker] || { firstMs: t, lastMs: t };
        rec.lastMs = t;
        S.namesSeen[parsed.speaker] = rec;
      }
    }

    // Anything no longer rendered is finished.
    for (const c of S.captions) {
      if (!c.done && !active.has(c.id)) c.done = true;
    }

    // Keep memory bounded on marathon meetings; Python has already drained.
    if (S.captions.length > 4000) {
      S.captions = S.captions.slice(-2000);
    }
  }

  let captionTimer = null;
  
  /* Helper function to check if captions are currently enabled */
  window.__aiBotCheckCaptionsEnabled = function () {
    try {
      // Check if caption container exists and is visible
      const captionContainer = document.querySelector('[jsname="dsyhDe"]') || 
                               document.querySelector('[class*="caption" i]') ||
                               document.querySelector('[aria-live="assertive"]');
      return !!captionContainer;
    } catch (e) {
      return false;
    }
  };
  
  /* Force enable captions via JavaScript if possible */
  window.__aiBotForceEnableCaptions = function () {
    try {
      // Try to find and click the captions button
      const selectors = [
        '[aria-label*="Turn on captions" i]',
        '[aria-label*="captions" i]',
        'button[aria-label*="Turn on captions" i]',
        'button[aria-label*="captions" i]',
        '[jsname][aria-label*="caption" i]',
        'div[role="button"][aria-label*="caption" i]',
      ];
      
      for (const sel of selectors) {
        const btn = document.querySelector(sel);
        if (btn) {
          // Check if button text/label indicates captions are OFF
          const label = btn.getAttribute('aria-label') || btn.textContent || '';
          if (label.toLowerCase().includes('turn on') || 
              label.toLowerCase().includes('enable')) {
            btn.click();
            return { enabled: true, method: sel };
          }
        }
      }
      
      return { enabled: false, reason: 'No caption button found' };
    } catch (e) {
      return { enabled: false, error: e.toString() };
    }
  };
  
  window.__aiBotStartCaptions = function () {
    if (captionTimer) return true;
    
    // Try to force enable captions first
    try {
      const result = window.__aiBotForceEnableCaptions();
      if (result.enabled) {
        note('Captions force-enabled: ' + result.method);
      }
    } catch (e) {
      note('Force enable failed: ' + e);
    }
    
    captionTimer = setInterval(() => {
      try {
        pollCaptions();
      } catch (e) {
        note("pollCaptions: " + e);
      }
    }, 500);
    return true;
  };

  /* Returns every caption entry newer than `sinceId`, plus any still-open
   * entry regardless of age (its text is still growing). Python keeps the
   * watermark, so each poll transfers only what can still change. */
  window.__aiBotDrainCaptions = function (sinceId) {
    const since = sinceId || 0;
    const out = [];
    for (const c of S.captions) {
      if (c.id > since || !c.done) {
        out.push({
          id: c.id,
          speaker: c.speaker,
          text: c.text,
          startMs: c.startMs,
          endMs: c.endMs,
          done: c.done,
          rev: c.rev,
        });
      }
    }
    return out;
  };

  window.__aiBotAllCaptions = function () {
    return S.captions.map((c) => ({
      id: c.id,
      speaker: c.speaker,
      text: c.text,
      startMs: c.startMs,
      endMs: c.endMs,
    }));
  };

  // ═══════════════════════ 3. PRESENCE / LIFECYCLE ══════════════════════

  function q(sel) {
    try {
      return document.querySelector(sel);
    } catch (e) {
      return null;
    }
  }

  function inCall() {
    return !!(
      q('[aria-label*="Leave call" i]') ||
      q('button[aria-label*="Leave call" i]') ||
      q('[data-tooltip-id="tooltip-meeting-details"]') ||
      q("[data-participant-id]")
    );
  }

  const END_PHRASES = [
    "you've left the meeting",
    "you have left the meeting",
    "return to home screen",
    "you've been removed",
    "you have been removed",
    "removed from the meeting",
    "this call has ended",
    "the call ended",
    "meeting ended",
    "call ended",
    "your host ended the meeting",
    "no one responded to your request",
    "you can't join this",
    "you were denied",
    "someone in the call denied",
    "you're the only one here",
    "you are the only one here",
    "everyone else has left",
    "everyone else left",
    "ready to leave?",
    "just you",
    "leaving in 1 min",
    "leaving soon",
  ];

  function endedInfo() {
    let text = "";
    try {
      // Read entire document body without truncating so bottom alerts are captured
      text = (document.body ? document.body.innerText || "" : "").toLowerCase();
    } catch (e) {
      return { ended: false, reason: null };
    }
    for (const p of END_PHRASES) {
      if (text.includes(p)) return { ended: true, reason: p };
    }
    return { ended: false, reason: null };
  }

  function participantInfo() {
    let others = 0;
    let tileTotal = 0;
    let selfSeen = false;
    let domCount = null;
    const names = [];

    // 1. Google Meet People button: Ground truth for room head count
    try {
      const peopleBtns = document.querySelectorAll(
        'button[aria-label*="people" i], button[aria-label*="everyone" i], button[aria-label*="participant" i], [data-panel-id="1"]'
      );
      for (const b of peopleBtns) {
        const aria = (b.getAttribute("aria-label") || "").trim();
        const text = (b.innerText || "").trim();
        
        // Match numbers in aria-label, e.g. "Show everyone (1)", "People (2)", "2 people"
        const m = aria.match(/(?:everyone|people|participants)[^\d]*(\d+)/i)
               || aria.match(/\((\d+)\)/)
               || text.match(/^(\d+)$/)
               || (aria + " " + text).match(/(\d+)/);

        if (m) {
          const total = parseInt(m[1], 10);
          if (total >= 1 && total < 1000) {
            domCount = total;
            // Total includes the bot itself. If total is 1, exactly 0 other humans exist!
            others = Math.max(0, total - 1);
            break;
          }
        }
      }
    } catch (e) {
      note("people button: " + e);
    }

    // 2. Video / Avatar tiles in Google Meet DOM
    try {
      const tileEls = document.querySelectorAll(
        '[data-participant-id], [data-requested-participant-id], div[data-tile-id], div[data-allocation-index]'
      );
      const uniqueIds = new Set();
      tileEls.forEach((el) => {
        const id = el.getAttribute("data-participant-id") || el.getAttribute("data-requested-participant-id") || el.getAttribute("data-tile-id");
        if (id) uniqueIds.add(id);

        if (el.hasAttribute("data-self-name") || el.querySelector("[data-self-name]") || el.hasAttribute("data-is-self")) {
          selfSeen = true;
        }

        const label =
          el.getAttribute("data-participant-name") ||
          (el.querySelector("[data-self-name]") &&
            el.querySelector("[data-self-name]").getAttribute("data-self-name")) ||
          "";
        const nm = (label || "").trim();
        if (nm) names.push(nm);
      });

      tileTotal = uniqueIds.size;

      // If we didn't get an explicit head count from the people button, deduce from tiles
      if (domCount === null && tileTotal > 0) {
        others = Math.max(0, tileTotal - (selfSeen ? 1 : 0));
      }
    } catch (e) {
      note("tiles: " + e);
    }

    // 3. Meet "Alone" prompts & banners ("You're the only one here", "Everyone else left")
    let aloneDetected = false;
    try {
      const fullText = (document.body ? document.body.innerText || "" : "").toLowerCase();
      const aloneTriggers = [
        "you're the only one here",
        "you are the only one here",
        "everyone else has left",
        "everyone else left",
        "ready to leave?",
        "leaving in 1 min",
        "leaving in 60s",
        "just you",
      ];
      for (const phrase of aloneTriggers) {
        if (fullText.includes(phrase)) {
          aloneDetected = true;
          others = 0;
          break;
        }
      }
    } catch (e) {
      note("alone check: " + e);
    }

    // Live remote tracks count (kept for audio diagnostics ONLY, NEVER overrides others)
    const live = countLiveTracks();
    const captionNames = Object.keys(S.namesSeen).filter((n) => n && n !== "You");

    return {
      others,
      domCount,
      tileTotal,
      aloneDetected: aloneDetected || (tileTotal === 1 && selfSeen) || (domCount !== null && domCount === 1),
      liveRemoteTracks: live,
      names: Array.from(new Set(names.concat(captionNames))).slice(0, 50),
      selfSeen,
    };
  }

  window.__aiBotStatus = function () {
    const ended = endedInfo();
    const p = participantInfo();
    return {
      inCall: inCall(),
      ended: ended.ended,
      endedReason: ended.reason,
      recording: S.recording,
      recordedMs: S.recStartedAt ? relMs() : 0,
      bytesSent: S.bytesSent,
      chunksSent: S.chunksSent,
      pcmTapActive: S.pcmTapActive,
      pcmSampleRate: S.pcmSampleRate,
      pcmSamplesSent: S.pcmSamplesSent,
      pcmChunksSent: S.pcmChunksSent,
      audioGraphReady: S.audioGraphReady,
      audioContextState: ac ? ac.state : "none",
      audioLevelPeak: S.audioLevelPeak,
      audioLevelRecent: S.audioLevelRecent,
      remoteAudioTracks: S.remoteTracks.size,
      captionCount: S.captions.length,
      participants: p,
      errors: S.errors.slice(-5),
    };
  };

  window.__aiBotNames = function () {
    return S.namesSeen;
  };

  /* Get detailed participant list from Google Meet for speaker identification.
   * Returns array of participant names extracted from DOM. */
  window.__aiBotGetParticipants = function () {
    const participants = [];
    const seen = new Set();

    try {
      // Method 1: Extract from participant tiles
      const tileSelectors = [
        '[data-participant-id]',
        '[data-requested-participant-id]',
        'div[data-tile-id]',
        '[data-participant-name]',
      ];

      tileSelectors.forEach((selector) => {
        try {
          const tiles = document.querySelectorAll(selector);
          tiles.forEach((tile) => {
            // Try multiple attributes for name
            const name =
              tile.getAttribute('data-participant-name') ||
              tile.getAttribute('data-requested-participant-name') ||
              tile.getAttribute('aria-label') ||
              '';

            const cleaned = name.replace(/\s*\(you\)\s*/i, '').trim();
            if (cleaned && cleaned !== 'You' && cleaned.length > 1 && !seen.has(cleaned)) {
              participants.push(cleaned);
              seen.add(cleaned);
            }

            // Also check for name in nested elements
            const nameElem = tile.querySelector('[data-self-name], [aria-label]');
            if (nameElem) {
              const nestedName = nameElem.getAttribute('data-self-name') || nameElem.getAttribute('aria-label') || '';
              const cleanedNested = nestedName.replace(/\s*\(you\)\s*/i, '').trim();
              if (cleanedNested && cleanedNested !== 'You' && cleanedNested.length > 1 && !seen.has(cleanedNested)) {
                participants.push(cleanedNested);
                seen.add(cleanedNested);
              }
            }
          });
        } catch (e) {
          note('participant tile extraction: ' + e);
        }
      });

      // Method 2: Extract from participant panel (if open)
      try {
        const panelItems = document.querySelectorAll(
          '[data-participant-id] [role="listitem"], [data-panel-id="1"] [role="listitem"]'
        );
        panelItems.forEach((item) => {
          const text = (item.textContent || '').trim();
          // Names are usually short (2-50 chars) and don't contain weird characters
          if (text && text.length >= 2 && text.length <= 50 && /^[a-zA-Z0-9\s\-'\.]+$/.test(text)) {
            const cleaned = text.replace(/\s*\(you\)\s*/i, '').trim();
            if (cleaned && cleaned !== 'You' && !seen.has(cleaned)) {
              participants.push(cleaned);
              seen.add(cleaned);
            }
          }
        });
      } catch (e) {
        note('participant panel extraction: ' + e);
      }

      // Method 3: Extract from caption speaker names (Google learned voices)
      Object.keys(S.namesSeen).forEach((name) => {
        if (name && name !== 'You' && name.length > 1 && !seen.has(name)) {
          participants.push(name);
          seen.add(name);
        }
      });

    } catch (e) {
      note('__aiBotGetParticipants: ' + e);
    }

    return participants;
  };

  /* Click away the interstitials Meet throws up ("Got it", "Dismiss",
   * "Continue without microphone and camera", ...). Returns what it clicked
   * so the bot can log it. */
  window.__aiBotDismissDialogs = function () {
    const clicked = [];
    const patterns = [
      /^got it$/i,
      /^dismiss$/i,
      /^ok$/i,
      /^okay$/i,
      /^close$/i,
      /^no thanks$/i,
      /^not now$/i,
      /^allow$/i,
      /^continue$/i,
      /^continue without microphone and camera$/i,
      /^continue without microphone$/i,
      /^continue without camera$/i,
      /^use microphone and camera$/i,
      /^join now$/i,
    ];
    try {
      const buttons = Array.from(
        document.querySelectorAll('button, [role="button"]')
      ).slice(0, 400);
      for (const b of buttons) {
        const label = (b.innerText || b.getAttribute("aria-label") || "")
          .replace(/\s+/g, " ")
          .trim();
        if (!label) continue;
        if (patterns.some((re) => re.test(label))) {
          const box = b.getBoundingClientRect();
          if (box.width === 0 || box.height === 0) continue;
          b.click();
          clicked.push(label);
          if (clicked.length >= 3) break;
        }
      }
    } catch (e) {
      note("dismissDialogs: " + e);
    }
    return clicked;
  };

  /* Turn the bot's own mic and camera off. Silences the synthetic capture
   * device so the bot is a silent, invisible observer. */
  window.__aiBotMuteSelf = function () {
    const done = [];
    try {
      const targets = [
        ['[aria-label*="Turn off microphone" i]', "mic"],
        ['[aria-label*="Turn off camera" i]', "cam"],
        ['[data-is-muted="false"][aria-label*="microphone" i]', "mic2"],
        ['[data-is-muted="false"][aria-label*="camera" i]', "cam2"],
      ];
      for (const [sel, tag] of targets) {
        const el = q(sel);
        if (el) {
          const box = el.getBoundingClientRect();
          if (box.width > 0 && box.height > 0) {
            el.click();
            done.push(tag);
          }
        }
      }
    } catch (e) {
      note("muteSelf: " + e);
    }
    return done;
  };

  window.__aiBotLeave = function () {
    try {
      const el =
        q('[aria-label*="Leave call" i]') || q('button[aria-label*="Leave call" i]');
      if (el) {
        el.click();
        setTimeout(() => {
          try {
            const confirm = q('button[aria-label*="Just leave" i]') || Array.from(document.querySelectorAll('button')).find(b => /just leave/i.test(b.innerText || ''));
            if (confirm) confirm.click();
          } catch (e) {}
        }, 300);
        return true;
      }
    } catch (e) {
      note("leave: " + e);
    }
    return false;
  };

  // Keep the AudioContext alive across Meet's own audio juggling.
  try {
    setInterval(resumeAudio, 5000);
    document.addEventListener("click", resumeAudio, { capture: true, passive: true });
  } catch (e) {
    /* ignore */
  }

  // Build the graph as early as possible so the recorder can start the moment
  // the bot is admitted.
  try {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => ensureAudioGraph(), {
        once: true,
      });
    } else {
      ensureAudioGraph();
    }
  } catch (e) {
    /* ignore */
  }
})();
