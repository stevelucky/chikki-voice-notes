"""Multi-engine transcription: Whisper (mlx), IndicWhisper (ai4bharat), Parakeet (mlx).

Engine is selected via config.yaml -> transcription.engine.
Each engine has its own model path and invocation method.
"""

from .config import CONFIG


def _transcribe_whisper(audio_path: str, model: str, language: str) -> dict:
    import os
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    import mlx_whisper

    result = mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=model,
        language=language,
        task="transcribe",
        word_timestamps=True,
    )
    return {
        "text": result.get("text", "").strip(),
        "segments": result.get("segments", []),
        "language": result.get("language", language),
    }


def _transcribe_indicwhisper(audio_path: str, model: str, language: str) -> dict:
    """IndicWhisper uses the same whisper architecture but fine-tuned weights.

    It's compatible with the transformers/mlx-whisper pipeline — the HuggingFace
    model is a standard whisper checkpoint. We try mlx_whisper first (fast on
    Apple Silicon), fall back to transformers if the model isn't in MLX format.
    """
    try:
        import mlx_whisper

        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=model,
            language=language,
            task="transcribe",
            word_timestamps=True,
        )
        return {
            "text": result.get("text", "").strip(),
            "segments": result.get("segments", []),
            "language": result.get("language", language),
        }
    except Exception as e:
        print(f"[transcriber]", file=__import__('sys').stderr); print(f"[transcriber] mlx_whisper failed for IndicWhisper ({e}), falling back to transformers")
        import torch
        from transformers import WhisperProcessor, WhisperForConditionalGeneration
        import soundfile as sf

        processor = WhisperProcessor.from_pretrained(model)
        model_obj = WhisperForConditionalGeneration.from_pretrained(model)

        audio, sr = sf.read(audio_path)
        # Resample to 16kHz if needed
        if sr != 16000:
            import numpy as np
            from scipy.signal import resample

            num_samples = int(len(audio) * 16000 / sr)
            audio = resample(audio, num_samples)
            sr = 16000

        input_features = processor(audio, sampling_rate=sr, return_tensors="pt").input_features

        with torch.no_grad():
            predicted_ids = model_obj.generate(input_features)

        text = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
        return {
            "text": text.strip(),
            "segments": [],
            "language": language,
        }


def _transcribe_parakeet(audio_path: str, model: str, language: str) -> dict:
    """Parakeet MLX — NVIDIA's ASR model ported to Apple Silicon.

    Uses the parakeet-mlx package (pip install parakeet-mlx).
    """
    from parakeet_mlx import transcribe as pk_transcribe

    result = pk_transcribe(audio_path)
    text = result if isinstance(result, str) else result.get("text", str(result))
    return {
        "text": text.strip(),
        "segments": [],
        "language": "en",  # Parakeet is English-only
    }


_ENGINES = {
    "whisper": _transcribe_whisper,
    "indicwhisper": _transcribe_indicwhisper,
    "parakeet": _transcribe_parakeet,
}


class Transcriber:
    def __init__(self, engine: str = None):
        self._cfg = CONFIG["transcription"]
        self._engine_name = engine or self._cfg["engine"]
        self._language = self._cfg.get("language", "en")

        engine_cfg = self._cfg.get("engines", {}).get(self._engine_name)
        if not engine_cfg:
            raise ValueError(
                f"Unknown engine '{self._engine_name}'. "
                f"Available: {', '.join(self._cfg.get('engines', {}).keys())}"
            )
        self._model = engine_cfg["model"]
        self._engine_fn = _ENGINES[self._engine_name]

    @property
    def engine_name(self):
        return self._engine_name

    @property
    def model_name(self):
        return self._model

    def transcribe(self, audio_path: str) -> dict:
        """Transcribe an audio file. Returns dict with 'text', 'segments', 'language'."""
        import sys
        print(f"[transcriber] Engine: {self._engine_name} | Model: {self._model}", file=sys.stderr)
        print(f"[transcriber] Transcribing: {audio_path}", file=sys.stderr)

        result = self._engine_fn(audio_path, self._model, self._language)

        print(f"[transcriber] Done. {len(result['text'])} chars.", file=sys.stderr)
        return result

    @staticmethod
    def available_engines() -> dict:
        """Return dict of engine_name -> description from config."""
        engines = CONFIG["transcription"].get("engines", {})
        return {name: cfg.get("description", "") for name, cfg in engines.items()}
