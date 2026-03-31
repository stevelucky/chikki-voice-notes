"""Post-transcription cleaning: removes Whisper hallucinations and formats transcript.

Whisper commonly hallucinates during silence or noise:
- Repeated words/phrases ("saf saf saf saf...")
- Looping sentences ("It's a lot of money. It's a lot of money.")
- Gibberish tokens during background noise
"""

import re
import sys


def clean_transcript(transcript: dict) -> dict:
    """Clean transcript text and segments. Returns a new dict with cleaned data."""
    text = transcript.get("text", "")
    segments = transcript.get("segments", [])

    # Clean segments first (they have more granular info)
    if segments:
        cleaned_segments = _clean_segments(segments)
        # Rebuild text from cleaned segments
        cleaned_text = " ".join(s.get("text", "").strip() for s in cleaned_segments if s.get("text", "").strip())
    else:
        cleaned_text = text
        cleaned_segments = segments

    # Apply text-level cleaning
    cleaned_text = _clean_text(cleaned_text)

    orig_len = len(text)
    new_len = len(cleaned_text)
    if orig_len > 0 and (orig_len - new_len) > 50:
        print(f"[cleaner] Removed {orig_len - new_len} chars of noise ({100 * (orig_len - new_len) / orig_len:.0f}%)", file=sys.stderr)

    return {
        "text": cleaned_text,
        "segments": cleaned_segments,
        "language": transcript.get("language", "en"),
    }


def _clean_text(text: str) -> str:
    """Remove repeated words, phrases, and gibberish from transcript text."""
    # Remove runs of the same short word repeated 4+ times: "saf saf saf saf..." → ""
    text = re.sub(r'\b(\w{1,8})\s+(?:\1\s+){3,}(\1)?', '', text)

    # Remove runs of the same sentence repeated 3+ times
    # "It's a lot of money. It's a lot of money. It's a lot of money." → "It's a lot of money."
    text = re.sub(r'((?:[A-Z][^.!?]*[.!?])\s*)\1{2,}', r'\1', text)

    # Remove runs of the same short phrase repeated 3+ times (without punctuation)
    text = re.sub(r'((?:\S+\s+){2,6}?)\1{2,}', r'\1', text)

    # Collapse excessive whitespace
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'\s+([.!?,])', r'\1', text)

    return text.strip()


def _clean_segments(segments: list) -> list:
    """Filter out hallucinated segments based on Whisper's quality signals."""
    cleaned = []
    prev_text = ""

    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue

        # Skip segments with very high compression ratio (hallucination signal)
        compression = seg.get("compression_ratio", 1.0)
        if compression and compression > 2.8:
            continue

        # Skip segments with very low average log probability (low confidence)
        avg_logprob = seg.get("avg_logprob", 0.0)
        if avg_logprob and avg_logprob < -1.2:
            continue

        # Skip segments marked with high no-speech probability
        no_speech = seg.get("no_speech_prob", 0.0)
        if no_speech and no_speech > 0.7:
            continue

        # Skip if this segment's text is identical to the previous one (stuck loop)
        if text == prev_text:
            continue

        # Check for internal repetition within the segment
        words = text.split()
        if len(words) > 6:
            unique_ratio = len(set(words)) / len(words)
            if unique_ratio < 0.25:  # Less than 25% unique words = repetitive garbage
                continue

        cleaned.append(seg)
        prev_text = text

    return cleaned


def format_transcript_text(transcript: dict) -> str:
    """Format transcript into readable paragraphs using segment timestamps.

    Groups segments into paragraphs based on time gaps (>2s pause = new paragraph).
    Adds timestamps every ~60s for navigation.
    """
    segments = transcript.get("segments", [])
    if not segments:
        # No segments — just wrap text into paragraphs by sentence count
        text = transcript.get("text", "")
        return _wrap_into_paragraphs(text)

    paragraphs = []
    current_para = []
    current_para_start = None
    last_end = 0.0

    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue

        start = seg.get("start", 0.0)
        end = seg.get("end", start)

        # New paragraph on >2s gap
        if current_para and (start - last_end) > 2.0:
            ts = _format_ts(current_para_start or 0)
            paragraphs.append(f"**[{ts}]** " + " ".join(current_para))
            current_para = []
            current_para_start = None

        if current_para_start is None:
            current_para_start = start

        current_para.append(text)
        last_end = end

        # Also break every ~60s for readability
        if current_para_start is not None and (end - current_para_start) > 60.0:
            ts = _format_ts(current_para_start)
            paragraphs.append(f"**[{ts}]** " + " ".join(current_para))
            current_para = []
            current_para_start = None

    # Flush remaining
    if current_para:
        ts = _format_ts(current_para_start or 0)
        paragraphs.append(f"**[{ts}]** " + " ".join(current_para))

    return "\n\n".join(paragraphs)


def _wrap_into_paragraphs(text: str, sentences_per_para: int = 4) -> str:
    """Split plain text into paragraphs by sentence count."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    paragraphs = []
    for i in range(0, len(sentences), sentences_per_para):
        chunk = " ".join(sentences[i:i + sentences_per_para])
        if chunk.strip():
            paragraphs.append(chunk.strip())
    return "\n\n".join(paragraphs)


def _format_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
