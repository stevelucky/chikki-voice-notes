"""LLM-based processing of transcripts into structured meeting notes.

Loads prompt templates from prompts.json. Meeting type selectable via --type flag.
Supports multiple LLM providers: gemini, openai, anthropic — set via config.yaml.
"""

import json
import os
import sys

from google import genai
from google.genai import types as genai_types
from openai import OpenAI
from anthropic import Anthropic
from datetime import datetime
from .config import CONFIG

_CHUNK_SECTION_PROMPT = """You are summarizing one section of a longer meeting transcript.

This is section {section_num} of {total_sections}, covering minutes {start_min}-{end_min} of the meeting.

Return JSON with this exact shape:
{{
  "section_title": "<short title describing what this section was about>",
  "summary": "<2-4 sentence summary of what happened in this section>",
  "decisions": ["<decision made in this section>", ...],
  "action_items": [{{"task": "<what>", "owner": "<who, or null>", "due": "<when, or null>"}}, ...],
  "key_points": ["<important point discussed>", ...],
  "open_threads": ["<unresolved question or topic to revisit>", ...]
}}

Rules:
- Only include items actually present in this section. Empty arrays are fine.
- Do not invent owners or dates. Use null when not stated.
- Be concise. No filler."""

_CHUNK_SYNTHESIS_PROMPT = """You are synthesizing a long meeting from per-section summaries.

You will receive a JSON array of section summaries. Produce a single final note in JSON with this shape:
{{
  "executive_summary": "<3-5 sentence summary of the whole meeting>",
  "sections": [
    {{"title": "<section title>", "summary": "<the section's summary>", "minutes": "<start-end>"}}, ...
  ],
  "decisions": ["<deduplicated decision across the whole meeting>", ...],
  "action_items": [{{"task": "<what>", "owner": "<who or null>", "due": "<when or null>"}}, ...],
  "key_points": ["<deduplicated key point>", ...],
  "open_threads": ["<deduplicated unresolved item>", ...]
}}

Rules:
- Deduplicate aggressively. If section 1 and section 3 both flag the same action item, list it once.
- Preserve the chronological order of sections.
- The executive summary should read as one coherent narrative, not a list of section recaps.
- Do not invent items. Only consolidate what's already in the section summaries."""


_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROMPTS_PATH = os.path.join(_BASE_DIR, "prompts.json")


def load_prompts() -> dict:
    with open(_PROMPTS_PATH) as f:
        prompts = json.load(f)
    prompts.pop("_description", None)
    return prompts


def available_types() -> dict:
    """Return dict of type_key -> {name, description}."""
    prompts = load_prompts()
    return {k: {"name": v["name"], "description": v["description"]} for k, v in prompts.items()}


def _call_llm(provider: str, model: str, system_prompt: str, prompt: str, temperature: float) -> str:
    """Dispatch an LLM call to the configured provider. Returns raw response text."""
    if provider == "gemini":
        client = genai.Client()
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                response_mime_type="application/json",
            ),
        )
        return response.text

    elif provider == "openai":
        client = OpenAI()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    elif provider == "anthropic":
        client = Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return response.content[0].text

    else:
        raise ValueError(
            f"Unknown LLM provider '{provider}'. Available: gemini, openai, anthropic"
        )


class Processor:
    def __init__(self, meeting_type: str = None):
        self._cfg = CONFIG["processing"]
        self._provider = self._cfg.get("provider", "gemini")
        self._model_name = self._cfg["model"]
        self._temperature = self._cfg.get("temperature", 0.3)

        prompts = load_prompts()
        self._type = meeting_type or self._cfg.get("default_type", "default")
        if self._type not in prompts:
            raise ValueError(
                f"Unknown meeting type '{self._type}'. "
                f"Available: {', '.join(prompts.keys())}"
            )
        self._system_prompt = prompts[self._type]["system_prompt"]
        self._type_name = prompts[self._type]["name"]

    @property
    def meeting_type(self):
        return self._type

    @property
    def type_name(self):
        return self._type_name

    def process(self, transcript_text: str, context: str = "") -> dict:
        """Process transcript text into structured notes using the configured LLM provider."""
        print(
            f"[processor] Provider: {self._provider} | Type: {self._type_name} | "
            f"Model: {self._model_name} | {len(transcript_text)} chars",
            file=sys.stderr,
        )

        prompt = f"Here is the transcript:\n\n{transcript_text}"
        prompt += f"\nToday's date is {datetime.now().strftime('%Y-%m-%d')}"
        if context:
            prompt += f"\n\nAdditional context: {context}"

        raw = _call_llm(self._provider, self._model_name, self._system_prompt, prompt, self._temperature)

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(raw[start:end])
            else:
                result = {
                    "title": "Untitled Recording",
                    "summary": raw,
                    "key_points": [],
                    "action_items": [],
                    "decisions": [],
                    "insights": [],
                    "topics": [],
                    "follow_ups": [],
                }

        result["_meeting_type"] = self._type
        print(f"[processor] Done. Title: {result.get('title', 'N/A')}", file=sys.stderr)
        return result

    @staticmethod
    def _split_segments_by_time(segments, chunk_seconds):
        """Group segments into time-based chunks. Each chunk is a list of segments
        whose start times fall within [chunk_idx * chunk_seconds, (chunk_idx+1) * chunk_seconds)."""
        if not segments:
            return []
        chunks = []
        current = []
        boundary = chunk_seconds
        for seg in segments:
            start = seg.get("start", 0)
            while start >= boundary:
                if current:
                    chunks.append(current)
                    current = []
                boundary += chunk_seconds
            current.append(seg)
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _parse_json_response(text):
        """Best-effort JSON parsing. Strips markdown fences, finds outermost braces."""
        import json, re as _re
        s = text.strip()
        # Strip ```json ... ``` fences
        s = _re.sub(r'^```(?:json)?\s*', '', s)
        s = _re.sub(r'\s*```$', '', s)
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            # Find first { and last }
            i = s.find('{')
            j = s.rfind('}')
            if i >= 0 and j > i:
                return json.loads(s[i:j+1])
            raise

    def process_chunked(self, transcript, context="", chunk_minutes=30):
        """Length-aware summarization for long meetings.
        Splits the transcript into time-based chunks, summarizes each section,
        then synthesizes the sections into a final exec-summary + per-section note.

        transcript: dict with 'text' and 'segments' (segments must have start/end/text)
        context: optional context string passed to each section
        chunk_minutes: chunk width in minutes (default 30)
        """
        segments = transcript.get("segments") or []
        text = transcript.get("text", "")

        if not segments:
            # No timestamps available — fall back to single-pass on the full text.
            return self.process(text, context=context)

        chunk_seconds = chunk_minutes * 60
        chunks = self._split_segments_by_time(segments, chunk_seconds)
        total = len(chunks)

        if total <= 1:
            # Meeting is shorter than one chunk — single pass is cheaper and just as good.
            return self.process(text, context=context)

        section_results = []
        for idx, chunk in enumerate(chunks, start=1):
            start_sec = chunk[0].get("start", 0)
            end_sec = chunk[-1].get("end", chunk[-1].get("start", 0))
            start_min = int(start_sec // 60)
            end_min = int(end_sec // 60)
            chunk_text = "\n".join(s.get("text", "").strip() for s in chunk if s.get("text"))

            system_prompt = _CHUNK_SECTION_PROMPT.format(
                section_num=idx,
                total_sections=total,
                start_min=start_min,
                end_min=end_min,
            )
            user_prompt = f"Meeting context: {context or 'none provided'}\n\nSection transcript:\n{chunk_text}"

            print(f"  [chunked] section {idx}/{total} ({start_min}-{end_min} min, {len(chunk_text)} chars)")
            response = self._call_llm(system_prompt, user_prompt)
            try:
                parsed = self._parse_json_response(response)
            except Exception as e:
                print(f"  [chunked] section {idx} JSON parse failed: {e}. Storing raw text.")
                parsed = {
                    "section_title": f"Section {idx}",
                    "summary": response,
                    "decisions": [],
                    "action_items": [],
                    "key_points": [],
                    "open_threads": [],
                }
            parsed["_minutes"] = f"{start_min}-{end_min}"
            section_results.append(parsed)

        # Synthesis pass
        import json as _json
        synthesis_user = f"Meeting context: {context or 'none provided'}\n\nSection summaries (JSON array):\n{_json.dumps(section_results, indent=2)}"
        print(f"  [chunked] synthesizing {total} sections")
        synthesis_response = self._call_llm(_CHUNK_SYNTHESIS_PROMPT, synthesis_user)
        try:
            final = self._parse_json_response(synthesis_response)
        except Exception as e:
            print(f"  [chunked] synthesis JSON parse failed: {e}. Returning sections only.")
            final = {
                "executive_summary": "Synthesis failed — see sections below.",
                "sections": [{"title": s.get("section_title", f"Section {i+1}"),
                              "summary": s.get("summary", ""),
                              "minutes": s.get("_minutes", "")} for i, s in enumerate(section_results)],
                "decisions": [d for s in section_results for d in s.get("decisions", [])],
                "action_items": [a for s in section_results for a in s.get("action_items", [])],
                "key_points": [k for s in section_results for k in s.get("key_points", [])],
                "open_threads": [o for s in section_results for o in s.get("open_threads", [])],
            }

        final["_chunked"] = True
        final["_section_count"] = total
        return final

