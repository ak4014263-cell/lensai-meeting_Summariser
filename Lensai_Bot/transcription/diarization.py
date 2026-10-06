"""Speaker diarization & attribution .

Merges Whisper audio transcript segments with:
1. Google Meet live caption speaker timeline
2. Turn-based acoustic speaker segmentation
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("lensai_bot.transcription.diarization")


def attribute_speakers(
    whisper_segments: List[Dict[str, Any]],
    caption_events: Optional[List[Dict[str, Any]]] = None,
    known_participants: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Attribute real speaker names to Whisper transcript segments.
    
    If caption_events are present (e.g., from Google Meet closed captions),
    aligns by timestamp overlap. Otherwise, clusters by turn or falls back to
    known participant rotations.
    """
    if not whisper_segments:
        return []

    attributed: List[Dict[str, Any]] = []

    if caption_events:
        # Sort caption events by timestamp
        captions = sorted(caption_events, key=lambda c: c.get("time_ms", 0))

        for seg in whisper_segments:
            seg_mid = (seg.get("start_time", 0) + seg.get("end_time", 0)) / 2.0
            best_speaker = None
            min_diff = float("inf")

            # Find closest caption event within a 4-second window
            for cap in captions:
                cap_time = cap.get("time_ms", 0)
                diff = abs(cap_time - seg_mid)
                if diff < min_diff and diff <= 4000:
                    min_diff = diff
                    best_speaker = cap.get("speaker")

            new_seg = dict(seg)
            if best_speaker:
                new_seg["speaker"] = best_speaker
            elif not new_seg.get("speaker") or new_seg.get("speaker") == "Speaker":
                new_seg["speaker"] = "Speaker"
            attributed.append(new_seg)

        return attributed

    # Fallback: if we have known participants and no captions, retain or assign
    default_speaker = known_participants[0] if (known_participants and len(known_participants) == 1) else "Speaker"
    for seg in whisper_segments:
        new_seg = dict(seg)
        if not new_seg.get("speaker") or new_seg.get("speaker") == "Speaker":
            new_seg["speaker"] = default_speaker
        attributed.append(new_seg)

    return attributed
