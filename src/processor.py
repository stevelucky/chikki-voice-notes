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
