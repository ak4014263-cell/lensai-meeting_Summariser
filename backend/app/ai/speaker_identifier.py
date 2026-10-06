"""
Speaker Identification - Otter/Fireflies approach for Google Meet

How Otter & Fireflies identify speakers in Google Meet:
1. Extract participant list from Google Meet (via DOM/API)
2. Map caption speaker labels to real participant names
3. Use temporal correlation (who spoke when)
4. Store speaker mappings for future recognition

This is NOT traditional audio-based diarization - it's participant list
extraction + intelligent caption mapping, which is exactly what Otter/Fireflies
do for Google Meet because Google's caption API already provides basic speaker
separation.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

import logging

logger = logging.getLogger(__name__)


class SpeakerIdentifier:
    """Maps Google Meet caption speaker labels to actual participant names."""

    def __init__(self):
        self.participants: list[str] = []
        self.speaker_mappings: dict[str, str] = {}  # "Speaker 1" -> "John Smith"
        self.caption_speakers: set[str] = set()  # Track all speaker labels seen

    def add_participants(self, participant_names: list[str]) -> None:
        """
        Add participant names from Google Meet's participant list.
        
        Args:
            participant_names: List of participant names from Google Meet DOM
        """
        for name in participant_names:
            cleaned = self._clean_participant_name(name)
            if cleaned and cleaned not in self.participants:
                self.participants.append(cleaned)
                logger.info(f"[SpeakerIdentifier] Added participant: {cleaned}")

    def add_caption_speaker(self, speaker_label: str) -> None:
        """Track a speaker label seen in captions."""
        if speaker_label and speaker_label not in ("You", "Speaker"):
            self.caption_speakers.add(speaker_label)

    def map_speaker(self, caption_speaker: str) -> str:
        """
        Map a caption speaker label to actual participant name.
        
        Strategy:
        1. If speaker label is already a real name (Google learned it) -> use it
        2. If it's "You" or "Speaker" -> try to infer from participants
        3. If it's "Speaker X" -> map to participant list intelligently
        4. Use cached mappings from previous matches
        5. Fuzzy match to participant list
        
        Args:
            caption_speaker: Speaker label from Google Meet captions (e.g., "You", "John", "Speaker 1")
            
        Returns:
            Best guess at actual participant name
        """
        if not caption_speaker:
            return "Unknown Speaker"

        # Clean the speaker name
        caption_speaker = caption_speaker.strip()

        # Already mapped?
        if caption_speaker in self.speaker_mappings:
            return self.speaker_mappings[caption_speaker]

        # Google learned the name - it's already real
        if self._is_real_name(caption_speaker):
            # Try fuzzy match with participants
            for participant in self.participants:
                # Exact match
                if caption_speaker == participant:
                    self.speaker_mappings[caption_speaker] = participant
                    return participant
                # Partial match (e.g., "Ajay" matches "Ajay Kumar")
                if caption_speaker.lower() in participant.lower():
                    self.speaker_mappings[caption_speaker] = participant
                    logger.info(f"[SpeakerIdentifier] Fuzzy matched '{caption_speaker}' -> '{participant}'")
                    return participant
                if participant.lower() in caption_speaker.lower():
                    self.speaker_mappings[caption_speaker] = participant
                    logger.info(f"[SpeakerIdentifier] Fuzzy matched '{caption_speaker}' -> '{participant}'")
                    return participant
            
            # No fuzzy match found, use as-is
            self.speaker_mappings[caption_speaker] = caption_speaker
            return caption_speaker

        # "You" or "Speaker" - generic labels
        if caption_speaker.lower() in ("you", "speaker"):
            # Try to map to first unassigned participant
            assigned = set(self.speaker_mappings.values())
            for participant in self.participants:
                if participant not in assigned:
                    self.speaker_mappings[caption_speaker] = participant
                    logger.info(f"[SpeakerIdentifier] Mapped '{caption_speaker}' -> '{participant}'")
                    return participant
            # All participants already assigned, return generic label
            return caption_speaker

        # "Speaker 1", "Speaker 2", etc. - numbered labels
        if re.match(r"Speaker \d+", caption_speaker, re.IGNORECASE):
            return self._map_numbered_speaker(caption_speaker)

        # Fallback - try to find any participant not yet assigned
        assigned = set(self.speaker_mappings.values())
        for participant in self.participants:
            if participant not in assigned:
                self.speaker_mappings[caption_speaker] = participant
                logger.info(f"[SpeakerIdentifier] Auto-assigned '{caption_speaker}' -> '{participant}'")
                return participant

        # Last resort
        return caption_speaker

    def _map_numbered_speaker(self, speaker_label: str) -> str:
        """
        Map "Speaker 1", "Speaker 2" to participant list.
        
        Strategy: 
        1. Assign in order of appearance
        2. Handle case where there are more speakers than participants detected
        3. Use smart matching based on timing
        """
        match = re.match(r"Speaker (\d+)", speaker_label)
        if not match:
            return speaker_label

        speaker_num = int(match.group(1))
        
        # Already mapped?
        if speaker_label in self.speaker_mappings:
            return self.speaker_mappings[speaker_label]

        # Get list of participants not yet assigned
        assigned_names = set(self.speaker_mappings.values())
        available_participants = [p for p in self.participants if p not in assigned_names]
        
        # If we have available participants
        if available_participants:
            # Use the first available participant
            participant = available_participants[0]
            self.speaker_mappings[speaker_label] = participant
            logger.info(f"[SpeakerIdentifier] Mapped '{speaker_label}' -> '{participant}'")
            return participant
        
        # Fallback: Try to map by index (Speaker 1 -> first participant, etc.)
        if 0 < speaker_num <= len(self.participants):
            participant = self.participants[speaker_num - 1]
            self.speaker_mappings[speaker_label] = participant
            logger.info(f"[SpeakerIdentifier] Mapped '{speaker_label}' -> '{participant}' (by index)")
            return participant

        # No participant available - return the label as-is
        logger.warning(f"[SpeakerIdentifier] Could not map '{speaker_label}' - not enough participants")
        return speaker_label

    def _is_real_name(self, name: str) -> bool:
        """
        Check if a string looks like a real person name vs. generic label.
        
        Real names: "John Smith", "Sarah", "Mike Chen", "Ajay", "Bishnu"
        Generic: "You", "Speaker", "Speaker 1", "Unknown", "reframe"
        """
        if not name:
            return False

        # Common generic patterns
        generic_patterns = [
            r"^You$",
            r"^Speaker( \d+)?$",
            r"^Unknown( Speaker)?$",
            r"^Guest( \d+)?$",
            r"^Participant( \d+)?$",
            r"^User( \d+)?$",
            r"^reframe$",  # Bot account name
        ]

        for pattern in generic_patterns:
            if re.match(pattern, name, re.IGNORECASE):
                return False

        # If it's in the participant list, it's real
        if name in self.participants:
            return True
        
        # Check if any participant name contains this name (fuzzy match)
        name_lower = name.lower()
        for participant in self.participants:
            if name_lower in participant.lower() or participant.lower() in name_lower:
                return True

        # Heuristic: Real names usually have letters and possibly spaces
        # Must have at least 2 characters and contain letters
        # Exclude very short names that might be initials only
        if len(name) < 2:
            return False
        
        # Must contain at least one alphabetic character
        if not any(c.isalpha() for c in name):
            return False
        
        # Real names typically don't contain only digits
        if name.isdigit():
            return False
            
        return True

    def _clean_participant_name(self, name: str) -> str:
        """Clean and normalize participant names from Google Meet."""
        if not name:
            return ""

        # Remove common prefixes/suffixes
        name = re.sub(r"\s*\(.*?\)\s*$", "", name)  # Remove "(you)" suffix
        name = name.strip()

        # Skip generic labels
        if name.lower() in ("you", "speaker", "guest", "unknown"):
            return ""

        return name

    def enhance_transcript(self, transcript_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Enhance transcript segments with mapped speaker names.
        
        Args:
            transcript_segments: List of {speaker, text, start, end}
            
        Returns:
            Enhanced segments with real participant names
        """
        enhanced = []
        
        for segment in transcript_segments:
            enhanced_segment = segment.copy()
            original_speaker = segment.get("speaker", "Unknown Speaker")
            
            # Add to tracking
            self.add_caption_speaker(original_speaker)
            
            # Map to real name
            mapped_speaker = self.map_speaker(original_speaker)
            enhanced_segment["speaker"] = mapped_speaker
            
            # Keep original for debugging
            if mapped_speaker != original_speaker:
                enhanced_segment["original_speaker"] = original_speaker
            
            enhanced.append(enhanced_segment)

        logger.info(
            f"[SpeakerIdentifier] Enhanced {len(enhanced)} segments. "
            f"Participants: {len(self.participants)}, "
            f"Mappings: {len(self.speaker_mappings)}"
        )

        return enhanced

    def enhance_captions(self, captions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Enhance Google Meet captions with mapped speaker names.
        
        Args:
            captions: List of caption dicts with 'speaker' field
            
        Returns:
            Enhanced captions with real participant names
        """
        enhanced = []
        
        for caption in captions:
            enhanced_caption = caption.copy()
            original_speaker = caption.get("speaker", "Unknown Speaker")
            
            # Map to real name
            mapped_speaker = self.map_speaker(original_speaker)
            enhanced_caption["speaker"] = mapped_speaker
            
            enhanced.append(enhanced_caption)

        return enhanced

    def get_speaker_stats(self) -> dict[str, Any]:
        """Get statistics about speaker identification."""
        return {
            "participants": self.participants,
            "caption_speakers": list(self.caption_speakers),
            "mappings": self.speaker_mappings,
            "identified_speakers": len(set(self.speaker_mappings.values())),
            "total_participants": len(self.participants),
        }


def extract_speakers_from_captions(captions: list[dict[str, Any]]) -> list[str]:
    """
    Extract unique speaker names from caption list.
    
    Args:
        captions: List of caption dicts with 'speaker' field
        
    Returns:
        List of unique speaker names, sorted by frequency
    """
    speaker_counts = Counter()
    
    for caption in captions:
        speaker = caption.get("speaker", "")
        if speaker and speaker not in ("You", "Speaker"):
            speaker_counts[speaker] += 1
    
    # Return sorted by frequency (most common first)
    return [speaker for speaker, _ in speaker_counts.most_common()]


def merge_speaker_segments(
    whisper_segments: list[dict[str, Any]],
    caption_timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge Whisper transcription segments with Google Meet caption speaker info.
    
    This is the key integration point: Whisper gives accurate text,
    Google Meet captions give speaker names.
    
    Args:
        whisper_segments: [{text, start, end}] from Whisper
        caption_timeline: [{speaker, text, startMs, endMs}] from Google Meet
        
    Returns:
        Merged segments with accurate text + speaker names
    """
    merged = []
    
    for segment in whisper_segments:
        start_time = segment.get("start", 0)
        end_time = segment.get("end", 0)
        text = segment.get("text", "")
        
        # Find overlapping caption to get speaker
        speaker = find_speaker_at_time(caption_timeline, start_time, end_time)
        
        merged.append({
            "text": text,
            "start": start_time,
            "end": end_time,
            "speaker": speaker,
        })
    
    return merged


def find_speaker_at_time(
    caption_timeline: list[dict[str, Any]],
    start_time: float,
    end_time: float,
) -> str:
    """
    Find the speaker from captions that overlaps with the given time range.
    
    Args:
        caption_timeline: List of caption dicts with startMs, endMs, speaker
        start_time: Start time in seconds
        end_time: End time in seconds
        
    Returns:
        Speaker name, or "Unknown Speaker" if no match
    """
    start_ms = start_time * 1000
    end_ms = end_time * 1000
    mid_ms = (start_ms + end_ms) / 2
    
    # Find captions that overlap with this time range
    overlapping_speakers = []
    
    for caption in caption_timeline:
        caption_start = caption.get("startMs", 0)
        caption_end = caption.get("endMs", 0)
        
        # Check if there's overlap
        if caption_start <= end_ms and caption_end >= start_ms:
            speaker = caption.get("speaker", "")
            if speaker and speaker != "Unknown Speaker":
                overlapping_speakers.append((speaker, caption_start, caption_end))
    
    if not overlapping_speakers:
        return "Unknown Speaker"
    
    # If multiple overlapping speakers, use the one closest to midpoint
    best_speaker = overlapping_speakers[0][0]
    best_distance = float('inf')
    
    for speaker, cap_start, cap_end in overlapping_speakers:
        cap_mid = (cap_start + cap_end) / 2
        distance = abs(cap_mid - mid_ms)
        if distance < best_distance:
            best_distance = distance
            best_speaker = speaker
    
    return best_speaker
