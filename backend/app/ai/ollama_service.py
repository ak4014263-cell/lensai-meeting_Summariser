"""Ollama-backed meeting intelligence.

Long meetings are never sent to the model as one giant prompt. The transcript
is split into overlapping chunks, each chunk is condensed into structured
notes ("map"), then the notes are synthesised into the final meeting result
("reduce"). This keeps every request inside the model's context window and
gives much better recall on hour-long calls.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

import ollama

from ..config import settings
# Performance monitoring imports - temporarily disabled
# from ..utils.performance_monitor import get_monitor
# from ..utils.retry_logic import retry_with_backoff, fallback_on_error

_client: ollama.Client | None = None


def get_client() -> ollama.Client:
    global _client
    if _client is None:
        _client = ollama.Client(host=settings.OLLAMA_HOST, timeout=settings.OLLAMA_TIMEOUT)
    return _client


def _options() -> dict[str, Any]:
    return {
        "num_ctx": settings.OLLAMA_NUM_CTX,
        "temperature": settings.OLLAMA_TEMPERATURE,
        "top_p": getattr(settings, "OLLAMA_TOP_P", 0.9),
        "top_k": getattr(settings, "OLLAMA_TOP_K", 40),
        "repeat_penalty": getattr(settings, "OLLAMA_REPEAT_PENALTY", 1.1),
    }


# @retry_with_backoff(max_attempts=3, initial_delay=2.0, exceptions=(Exception,))
def _chat(prompt: str, *, as_json: bool, system: str | None = None) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # monitor = get_monitor()
    # with monitor.measure("ollama_chat", as_json=as_json, prompt_length=len(prompt)):
    response = get_client().chat(
        model=settings.OLLAMA_MODEL,
        messages=messages,
        format="json" if as_json else None,
        options=_options(),
    )
    return response["message"]["content"]


# ─────────────────────────── JSON hardening ──────────────────────────────

def _extract_json(raw: str) -> dict[str, Any] | None:
    """Pull a JSON object out of a model response as forgivingly as possible."""
    if not raw:
        return None

    text = raw.strip()

    # Strip markdown fences if the model added them despite format="json".
    if "```" in text:
        fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
        if fenced:
            text = max(fenced, key=len).strip()

    candidates = [text]

    # Fall back to the outermost brace pair.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            # Trailing commas are the most common malformation.
            repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                parsed = json.loads(repaired)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return None


def _as_list(value: Any, limit: int = 40) -> list[str]:
    """Coerce whatever the model produced into a clean list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip(" -•\t") for p in re.split(r"[\n;]+", value)]
        items = [p for p in parts if p]
    elif isinstance(value, dict):
        items = [f"{k}: {v}" for k, v in value.items()]
    elif isinstance(value, list):
        items = []
        for entry in value:
            if isinstance(entry, str):
                items.append(entry.strip())
            elif isinstance(entry, dict):
                text = (
                    entry.get("text")
                    or entry.get("point")
                    or entry.get("topic")
                    or entry.get("decision")
                    or entry.get("question")
                    or entry.get("risk")
                    or entry.get("description")
                )
                if text:
                    items.append(str(text).strip())
                else:
                    items.append(json.dumps(entry, ensure_ascii=False))
            elif entry is not None:
                items.append(str(entry).strip())
    else:
        items = [str(value).strip()]

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = re.sub(r"\s+", " ", item).strip(" -•\t")
        if not cleaned or cleaned.lower() in ("none", "n/a", "null", "[]"):
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


_NULLISH = {"", "none", "null", "n/a", "na", "unknown", "unassigned", "tbd", "not specified"}


def _clean_field(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return None if text.lower() in _NULLISH else text


def _as_action_items(value: Any, limit: int = 40) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    entries = value if isinstance(value, list) else ([value] if value else [])

    for entry in entries:
        if isinstance(entry, str):
            text, owner, deadline = entry.strip(), None, None
            # Tolerate the "task | Owner: X | Deadline: Y" shape.
            if "|" in entry:
                head, *rest = [p.strip() for p in entry.split("|")]
                text = head
                for part in rest:
                    low = part.lower()
                    if low.startswith("owner"):
                        owner = part.split(":", 1)[-1].strip()
                    elif low.startswith(("deadline", "due")):
                        deadline = part.split(":", 1)[-1].strip()
        elif isinstance(entry, dict):
            text = entry.get("text") or entry.get("task") or entry.get("action") or entry.get("item")
            owner = entry.get("owner") or entry.get("assignee") or entry.get("who")
            deadline = entry.get("deadline") or entry.get("due") or entry.get("due_date")
        else:
            continue

        text = _clean_field(text)
        if not text:
            continue
        items.append(
            {
                "text": text,
                "owner": _clean_field(owner),
                "deadline": _clean_field(deadline),
            }
        )
        if len(items) >= limit:
            break

    # Deduplicate on task text.
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = item["text"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


# ───────────────────────────── chunking ──────────────────────────────────

def chunk_transcript(
    text: str,
    size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """Split a transcript on line boundaries into ~`size`-character chunks."""
    size = size or settings.LLM_CHUNK_CHARS
    overlap = overlap if overlap is not None else settings.LLM_CHUNK_OVERLAP_CHARS

    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > size and current:
            chunks.append("\n".join(current))
            if overlap > 0:
                # Carry the tail of this chunk into the next one for context.
                tail: list[str] = []
                tail_len = 0
                for prev in reversed(current):
                    if tail_len + len(prev) > overlap:
                        break
                    tail.insert(0, prev)
                    tail_len += len(prev) + 1
                current = tail
                current_len = tail_len
            else:
                current, current_len = [], 0
        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))

    if len(chunks) > settings.LLM_MAX_CHUNKS:
        # Extremely long transcript: keep the head and tail, which carry the
        # agenda and the conclusions.
        keep = settings.LLM_MAX_CHUNKS
        head = chunks[: keep // 2]
        tail = chunks[-(keep - len(head)) :]
        chunks = head + tail

    return chunks


# ────────────────────────────── prompts ──────────────────────────────────

_SYSTEM = (
    "You are a meticulous AI meeting analyst. You only use information present "
    "in the transcript you are given. You never invent names, dates or "
    "commitments. When a detail is absent you use null or omit it."
)

_MAP_PROMPT = """Below is PART {index} of {total} of a meeting transcript. Lines are formatted as "[mm:ss] Speaker: text".

Extract only what this part actually contains. Respond with a single JSON object and nothing else:

{{
  "notes": ["concise factual notes about what was discussed"],
  "decisions": ["decisions that were actually agreed - only if explicitly stated"],
  "action_items": [{{"text": "task", "owner": "name or null", "deadline": "when or null"}}],
  "topics": ["short topic labels"],
  "risks": ["risks, blockers or unresolved concerns"],
  "questions": ["important questions raised, answered or left open"]
}}

Important: Only include decisions if they were formally made. Use empty arrays for anything not present in this part. Do not speculate.

TRANSCRIPT PART {index}/{total}:
{chunk}
"""

_REDUCE_PROMPT = """You are given ordered structured notes extracted from consecutive parts of a single meeting transcript.

Merge them into one final comprehensive meeting report. Deduplicate overlapping items, keep the wording specific and detailed, and preserve owners and deadlines exactly as stated.

Respond with a single JSON object and nothing else:

{{
  "meeting_title": "Concise meeting title based on the main topic discussed (e.g., 'Q3 Roadmap Planning', 'Database Migration Discussion', 'Sprint Retrospective')",
  "executive_summary": "A detailed 4-6 sentence paragraph that thoroughly describes: (1) the main purpose and context of the meeting, (2) who the key participants were (use only first names like Ajay, Bishnu, Sarah), (3) what major topics were covered in depth, (4) the overall outcomes, conclusions, or direction decided upon. Include specific details about what was accomplished or discussed.",
  "key_points": [
    "Detailed discussion point 1 with full context about specific topic, explaining how it works and why it matters. The team emphasized key insights and their connections to broader objectives.",
    "Detailed discussion point 2 covering important concerns regarding a topic, with specific details mentioned. The group discussed various aspects and considered multiple options.",
    "Continue with 5-10 comprehensive key points covering all major discussions"
  ],
  "decisions": ["Formal decision 1 with full context and reasoning", "Decision 2 with implementation details"],
  "action_items": [{{"text": "detailed task description with context and expected outcome", "owner": "person name or null", "deadline": "date/time or null"}}],
  "topics": ["topic labels"],
  "risks": ["detailed risk or blocker with impact and context"],
  "questions": ["detailed question with context about why it matters"],
  "next_steps": ["detailed next step with who, what, when, and why"]
}}

CRITICAL INSTRUCTIONS for meeting_title:
- Create a short, descriptive title (3-8 words) that captures the main topic
- Examples: "Q4 Budget Planning", "Mobile App Design Review", "Customer Support Analysis"
- Base it on the actual content discussed, not generic phrases

CRITICAL INSTRUCTIONS for executive_summary:
- MUST be 4-6 complete sentences (minimum 200 words)
- Include WHO participated using ONLY FIRST NAMES (e.g., "Ajay", "Bishnu", "Sarah" not "Ajay Kumar" or "Bishnu Sharma")
- Include WHAT was the meeting about (specific topics, not generic)
- Include WHY the meeting happened (context, goals, objectives)
- Include KEY OUTCOMES (what was decided, discussed, or concluded)
- Be SPECIFIC with details from the transcript, not vague
- Example of GOOD: "The product team meeting led by Sarah focused on reviewing the Q3 roadmap priorities for the mobile app redesign project. Engineers Mike and Priya presented the technical architecture proposal for implementing the new authentication system, which they estimated would take 6 weeks to complete. The team extensively discussed tradeoffs between using OAuth2 versus implementing a custom solution, ultimately deciding that OAuth2 integration with Google and Apple Sign-In would provide better user experience. Marketing lead Jessica raised concerns about the timeline conflicting with the planned campaign launch in September, leading to an agreement to fast-track the social login features while deferring the email verification improvements to Q4."
- Example of BAD (too short): "The team discussed the mobile app and made some decisions about authentication."

CRITICAL INSTRUCTIONS for key_points:
- MUST include 8-12 detailed points (not just 2-3)
- EACH point should be 2-3 sentences with full context
- DO NOT include speaker names - focus on the content and insights discussed
- Include specific details, numbers, dates mentioned
- Connect points to show how discussion flowed
- Example of GOOD: "Significant concerns were raised about the proposed database migration timeline, noting that the current infrastructure couldn't handle the expected 10x increase in traffic during the holiday season. A phased rollout approach was suggested, starting with 10% of users in October, scaling to 50% by November, and completing the migration by December 1st. The team agreed this approach would minimize risk while still meeting the business objectives for the fiscal year."
- Example of BAD: "Database concerns were discussed and a phased approach was suggested."

Use empty arrays where there is genuinely nothing to report, but err on the side of INCLUDING details rather than omitting them. Never invent details that are not in the notes.

NOTES:
{notes}
"""

_SINGLE_PROMPT = """Below is the full transcript of a meeting. Lines are formatted as "[mm:ss] Speaker: text".

Analyse it deeply and respond with a single JSON object and nothing else:

{{
  "meeting_title": "Concise meeting title based on the main topic discussed (e.g., 'Q3 Roadmap Planning', 'Database Migration Discussion', 'Sprint Retrospective')",
  "executive_summary": "A detailed 4-6 sentence paragraph that thoroughly describes: (1) the main purpose and context of the meeting, (2) who the key participants were (use only first names like Ajay, Bishnu, Sarah), (3) what major topics were covered in depth, (4) the overall outcomes, conclusions, or direction decided upon. Include specific details about what was accomplished or discussed.",
  "key_points": [
    "Detailed discussion point 1 with full context about specific topic, explaining how it works and why it matters. The team emphasized key insights and connections to broader objectives.",
    "Detailed discussion point 2 covering important concerns regarding a topic, with specific details mentioned. The group discussed various aspects and considered multiple options.",
    "Continue with 8-12 comprehensive key points covering all major discussions"
  ],
  "decisions": ["Formal decision 1 with full context and reasoning", "Decision 2 with implementation details"],
  "action_items": [{{"text": "detailed task description with context and expected outcome", "owner": "person name or null", "deadline": "date/time or null"}}],
  "topics": ["topic labels"],
  "risks": ["detailed risk or blocker with impact and context"],
  "questions": ["detailed question with context about why it matters"],
  "next_steps": ["detailed next step with who, what, when, and why"]
}}

CRITICAL INSTRUCTIONS for executive_summary:
- MUST be 4-6 complete sentences (minimum 200 words)
- Include WHO participated (names and roles if mentioned)
- Include WHAT was the meeting about (specific topics, not generic)
- Include WHY the meeting happened (context, goals, objectives)
- Include KEY OUTCOMES (what was decided, discussed, or concluded)
- Be SPECIFIC with details from the transcript, not vague
- DO NOT write generic summaries like "The team discussed various topics"
- DO write detailed summaries like "The engineering team led by Sarah Chen convened to review the critical production incident that occurred on March 15th, which caused a 45-minute outage affecting 12,000 users..."

CRITICAL INSTRUCTIONS for key_points:
- MUST include 8-12 detailed points minimum (not just 2-3)
- EACH point should be 2-3 sentences with full context
- DO NOT include speaker names - focus on the content and insights discussed
- Include specific details, numbers, dates, technical terms mentioned
- Connect points to show how the discussion evolved
- Cover ALL significant topics discussed, not just highlights

CRITICAL INSTRUCTIONS for all fields:
- Be thorough and comprehensive, not brief
- Include specific names, numbers, dates, technical terms
- Provide context for why things matter
- Show relationships between different points
- Capture the depth and nuance of discussions

Use empty arrays where there is genuinely nothing to report, but err on the side of INCLUDING details rather than omitting them. Only use information from the transcript, but use ALL relevant information from it.

TRANSCRIPT:
{transcript}
"""


EMPTY_INSIGHTS: dict[str, Any] = {
    "executive_summary": "",
    "key_points": [],
    "decisions": [],
    "action_items": [],
    "topics": [],
    "risks": [],
    "questions": [],
    "next_steps": [],
    "model": settings.OLLAMA_MODEL,
}


def _ensure_summary(
    insights: dict[str, Any],
    transcript_text: str,
    report: Callable[[str], None],
) -> dict[str, Any]:
    """Guarantee a non-empty executive summary.

    The structured pass often returns a null summary even when it extracted
    other fields (common on short, noisy or non-English transcripts). A blank
    overview is poor UX, so backfill it: first from a prose LLM pass, then from
    the key points, then a generic note.
    """
    if (insights.get("executive_summary") or "").strip():
        return insights

    report("Executive summary was empty; generating a prose summary instead.")
    try:
        prose = _plain_text_fallback(transcript_text).get("executive_summary", "")
    except Exception:
        prose = ""

    if prose.strip():
        insights["executive_summary"] = prose.strip()
    elif insights.get("key_points"):
        insights["executive_summary"] = " ".join(insights["key_points"][:4])
    else:
        insights["executive_summary"] = (
            "A summary could not be generated automatically for this meeting, "
            "but the full transcript is available below."
        )
    return insights


def _normalise(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "meeting_title": (_clean_field(data.get("meeting_title")) or ""),
        "executive_summary": (_clean_field(data.get("executive_summary")) or ""),
        "key_points": _as_list(data.get("key_points")),
        "decisions": _as_list(data.get("decisions")),
        "action_items": _as_action_items(data.get("action_items")),
        "topics": _as_list(data.get("topics"), limit=25),
        "risks": _as_list(data.get("risks")),
        "questions": _as_list(data.get("questions")),
        "next_steps": _as_list(data.get("next_steps")),
        "model": settings.OLLAMA_MODEL,
    }


def check_available() -> tuple[bool, str]:
    """Verify Ollama is reachable and the configured model is present."""
    try:
        listed = get_client().list()
        names = []
        for entry in listed.get("models", []) or []:
            name = entry.get("model") or entry.get("name")
            if name:
                names.append(name)
        wanted = settings.OLLAMA_MODEL
        if any(n == wanted or n.split(":")[0] == wanted.split(":")[0] for n in names):
            return True, f"ollama ok, model '{wanted}' available"
        return False, (
            f"ollama reachable but model '{wanted}' is not installed "
            f"(installed: {', '.join(names) or 'none'}). Run: ollama pull {wanted}"
        )
    except Exception as exc:
        return False, f"ollama unreachable at {settings.OLLAMA_HOST}: {exc}"


def generate_meeting_insights(
    transcript_text: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Produce the structured meeting report for a transcript.

    Always returns a dict shaped like `EMPTY_INSIGHTS`. On total LLM failure
    the summary text explains what went wrong instead of raising, so the
    transcript is never lost.
    """

    def report(message: str) -> None:
        print(f"[AI] {message}")
        if progress:
            try:
                progress(message)
            except Exception:
                pass

    transcript_text = (transcript_text or "").strip()
    if not transcript_text:
        result = dict(EMPTY_INSIGHTS)
        result["executive_summary"] = "No speech was captured for this meeting."
        return result

    ok, detail = check_available()
    if not ok:
        report(detail)
        result = dict(EMPTY_INSIGHTS)
        result["executive_summary"] = (
            "The transcript was captured successfully, but the AI summary could "
            f"not be generated. {detail}"
        )
        return result

    # Start performance monitoring
    # monitor = get_monitor()
    start_time = time.time()
    
    chunks = chunk_transcript(transcript_text)

    try:
        if len(chunks) <= 1:
            report(f"Summarising with {settings.OLLAMA_MODEL} (single pass)...")
            
            # with monitor.measure("single_pass_summary", transcript_length=len(transcript_text)):
            raw = _chat(
                _SINGLE_PROMPT.format(transcript=chunks[0] if chunks else transcript_text),
                as_json=True,
                system=_SYSTEM,
            )
            parsed = _extract_json(raw)
            
            if parsed:
                result = _ensure_summary(_normalise(parsed), transcript_text, report)
                processing_time_ms = (time.time() - start_time) * 1000
                report(f"✓ Summary completed in {processing_time_ms:.0f}ms")
                # monitor.log_summary()
                return result
            
            report("Model did not return usable JSON; falling back to plain text.")
            return _plain_text_fallback(transcript_text)

        # ── map ──
        report(f"Long meeting: analysing {len(chunks)} transcript chunks...")
        notes: list[dict[str, Any]] = []
        
        for index, chunk in enumerate(chunks, start=1):
            report(f"Analysing chunk {index}/{len(chunks)}...")
            try:
                raw = _chat(
                    _MAP_PROMPT.format(index=index, total=len(chunks), chunk=chunk),
                    as_json=True,
                    system=_SYSTEM,
                )
                parsed = _extract_json(raw) or {}
            except Exception as exc:
                report(f"Chunk {index} failed ({exc}); continuing.")
                parsed = {}
            
            notes.append(
                {
                    "part": index,
                    "notes": _as_list(parsed.get("notes")),
                    "decisions": _as_list(parsed.get("decisions")),
                    "action_items": _as_action_items(parsed.get("action_items")),
                    "topics": _as_list(parsed.get("topics"), limit=15),
                    "risks": _as_list(parsed.get("risks")),
                    "questions": _as_list(parsed.get("questions")),
                }
            )

        # ── reduce ──
        report("Synthesising the final meeting report...")
        notes_blob = json.dumps(notes, ensure_ascii=False, indent=1)
        # Guard against the notes themselves overflowing the context window.
        budget = settings.LLM_CHUNK_CHARS * 3
        if len(notes_blob) > budget:
            notes_blob = notes_blob[:budget] + "\n... (notes truncated)"

        raw = _chat(_REDUCE_PROMPT.format(notes=notes_blob), as_json=True, system=_SYSTEM)
        parsed = _extract_json(raw)
        
        if parsed:
            merged = _normalise(parsed)
            # Union the mapped findings back in so nothing is silently dropped
            # by an over-eager synthesis pass.
            merged = _union_with_notes(merged, notes)
            result = _ensure_summary(merged, transcript_text, report)
            
            processing_time_ms = (time.time() - start_time) * 1000
            report(f"✓ Multi-chunk summary completed in {processing_time_ms:.0f}ms")
            # monitor.log_summary()
            return result

        report("Synthesis returned unusable JSON; assembling report from chunk notes.")
        return _ensure_summary(_assemble_from_notes(notes, transcript_text), transcript_text, report)

    except Exception as exc:
        report(f"Insight generation failed: {exc}")
        result = dict(EMPTY_INSIGHTS)
        result["executive_summary"] = (
            "The transcript was captured successfully, but the AI summary failed: "
            f"{exc}"
        )
        return result


def _union_with_notes(merged: dict[str, Any], notes: list[dict[str, Any]]) -> dict[str, Any]:
    def union(key: str, limit: int) -> None:
        seen = {item.lower() for item in merged.get(key, [])}
        for note in notes:
            for item in note.get(key, []):
                if len(merged[key]) >= limit:
                    return
                if item.lower() not in seen:
                    seen.add(item.lower())
                    merged[key].append(item)

    union("decisions", 30)
    union("risks", 25)
    union("questions", 25)
    union("topics", 25)

    existing = {item["text"].lower() for item in merged["action_items"]}
    for note in notes:
        for item in note.get("action_items", []):
            if len(merged["action_items"]) >= 40:
                break
            if item["text"].lower() not in existing:
                existing.add(item["text"].lower())
                merged["action_items"].append(item)
    return merged


def _assemble_from_notes(notes: list[dict[str, Any]], transcript_text: str) -> dict[str, Any]:
    """Build a usable report purely from the map stage output."""
    result = dict(EMPTY_INSIGHTS)
    result.update(
        {
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "topics": [],
            "risks": [],
            "questions": [],
            "next_steps": [],
        }
    )
    for note in notes:
        result["key_points"].extend(note.get("notes", []))
        result["decisions"].extend(note.get("decisions", []))
        result["action_items"].extend(note.get("action_items", []))
        result["topics"].extend(note.get("topics", []))
        result["risks"].extend(note.get("risks", []))
        result["questions"].extend(note.get("questions", []))

    result["key_points"] = _as_list(result["key_points"], limit=30)
    result["decisions"] = _as_list(result["decisions"], limit=30)
    result["action_items"] = _as_action_items(result["action_items"])
    result["topics"] = _as_list(result["topics"], limit=25)
    result["risks"] = _as_list(result["risks"], limit=25)
    result["questions"] = _as_list(result["questions"], limit=25)
    result["executive_summary"] = " ".join(result["key_points"][:5]) or (
        "A summary could not be generated, but the full transcript is available."
    )
    return result


def _plain_text_fallback(transcript_text: str) -> dict[str, Any]:
    """Last resort: ask for prose instead of JSON."""
    result = dict(EMPTY_INSIGHTS)
    try:
        excerpt = transcript_text[: settings.LLM_CHUNK_CHARS]
        raw = _chat(
            "Summarise this meeting transcript in 3-5 sentences. Plain prose, no "
            f"preamble.\n\n{excerpt}",
            as_json=False,
            system=_SYSTEM,
        )
        result["executive_summary"] = (_clean_field(raw) or "").strip()
    except Exception as exc:
        result["executive_summary"] = f"Summary generation failed: {exc}"
    return result


_LIVE_PROMPT = """You are an expert executive assistant taking precise, detailed live notes during a meeting that is STILL IN PROGRESS.

Below is the transcript so far (it may end mid-sentence). Write an accurate, comprehensive running summary that captures all important details for someone who just joined.

Format exactly like this, omitting any section that has nothing yet:

Overview:
<ONLY display the names of speakers who have spoken so far, e.g. "Speakers: Alice, Bob". Do not include any discussion or topics in this section.>

Discussion:
<3-4 detailed sentences covering the main topics discussed and context so far. Do NOT include speaker names in this section.>

Key points:
- <specific point with context. Do NOT include speaker names.>
- <specific point with context. Do NOT include speaker names.>

Decisions:
- <explicit decision made with context>

Action items:
- <specific task> (assigned to whom, deadline if mentioned)

Next topics to cover:
- <upcoming agenda items if mentioned>

IMPORTANT RULES:
- OVERVIEW: MUST ONLY display speaker names (e.g. "Speakers: Alice, Bob"). Do NOT write summary text or discussion in overview.
- DISCUSSION: Cover the main discussion topics and context, but do NOT include speaker names.
- KEY POINTS: Focus on substantive points and insights. Do NOT include speaker names.
- Be ACCURATE: Only use information directly from the transcript - never invent or assume.
- Be DETAILED: Capture important nuances, not just surface-level summary.
- Include timestamps or time references if important.
- Plain text format, no markdown headers.

TRANSCRIPT SO FAR:
{transcript}
"""


def summarise_live(transcript_text: str) -> str:
    """Fast, prose 'live notes' pass for an in-progress meeting.

    Deliberately not JSON: this runs repeatedly during the call, so it favours
    speed and robustness over structure. The authoritative structured report is
    produced once after the meeting ends.
    """
    text = (transcript_text or "").strip()
    if not text:
        return ""

    # Only summarise the most recent portion to keep latency low on long calls.
    budget = settings.LLM_CHUNK_CHARS
    if len(text) > budget:
        text = "... (earlier discussion omitted) " + text[-budget:]

    try:
        raw = _chat(_LIVE_PROMPT.format(transcript=text), as_json=False, system=_SYSTEM)
        res = (raw or "").strip()
        from .live_session import _clean_live_summary_speakers
        return _clean_live_summary_speakers(res)
    except Exception as exc:
        print(f"[AI] live summary failed: {exc}")
        return ""


def answer_question(context: str, question: str) -> str:
    """Answer a question strictly from the supplied transcript context."""
    if not (context or "").strip():
        return "There is no transcript for this meeting yet, so I can't answer that."

    ok, detail = check_available()
    if not ok:
        return f"The AI model is unavailable right now. {detail}"

    # Keep the retrieved context within the context window.
    budget = settings.LLM_CHUNK_CHARS * 2
    if len(context) > budget:
        context = context[:budget] + "\n... (transcript truncated)"

    prompt = f"""Answer the question using ONLY the meeting transcript below. Lines are formatted as "[mm:ss] Speaker: text".

Rules:
- If the transcript does not contain the answer, say exactly: "I don't have enough information from the meeting to answer that."
- Cite the timestamps you relied on, like (12:04).
- Be concise and specific.

TRANSCRIPT:
{context}

QUESTION: {question}
"""
    try:
        return _chat(prompt, as_json=False, system=_SYSTEM).strip()
    except Exception as exc:
        print(f"[AI] Q&A failed: {exc}")
        return f"Sorry, I couldn't reach the AI model: {exc}"
