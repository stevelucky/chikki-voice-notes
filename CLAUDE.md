# CLAUDE.md

## Project

Scribe — voice recording, transcription, and meeting notes pipeline for macOS.

## Stack

- Python 3.13, conda env `scribe`
- Recording: `sounddevice` + `soundfile` (incremental WAV writing, crash-safe)
- Transcription: `mlx-whisper` (default), `parakeet-mlx`, ai4bharat IndicWhisper
- LLM: Google Gemini / OpenAI / Anthropic (`google-genai` / `openai` / `anthropic`) — provider set via `config.yaml`, API key in `.env`
- Menu bar: Native Swift app (`menubar/`) with KeyboardShortcuts lib
- CLI: `click` with live progress timers
- Config: `config.yaml` (runtime settings) + `prompts.json` (meeting type templates)

## Architecture

Modular pipeline: `recorder -> transcriber -> processor -> output`

Each stage is independent. Transcriber supports multiple engines (whisper, indicwhisper, parakeet) swappable via config or `--engine` CLI flag. Processor loads meeting-type-specific prompts from `prompts.json` (default, standup, strategy, one_on_one, brainstorm, interview). Output writes a local markdown note (in `notes/`) plus the raw transcript as `.txt` and `.json` (in `transcripts/`) for reprocessing.

## Key Paths

- Config: `config.yaml` (all runtime settings)
- Prompts: `prompts.json` (meeting type templates — edit without code changes)
- API keys: `.env` (loaded by `src/config.py`)
- Notes output: `notes/`
- Raw transcripts: `transcripts/` (.txt + .json for reprocessing)
- Raw recordings: `recordings/`
- Swift menu bar app: `menubar/`
- ADRs: `docs/adr/`
- Improvements/roadmap: `docs/IMPROVEMENTS.md`

## Commands

```bash
conda activate scribe
python -m src.cli <command>
```

Commands: `quick`, `record`, `transcribe`, `process`, `reprocess`, `process-latest`, `correct`, `engines`, `types`, `menubar`, `list-notes`

`correct` regenerates a note from its original transcript with a plain-English correction as authoritative context (e.g. fixing a reversed speaker attribution); checked-off action items are preserved. `record --meter` streams live audio-band levels as JSON on stdout for the menu bar's equalizer.

Key flags: `--engine/-e` (transcription engine), `--type/-t` (meeting type), `--context/-c` (additional LLM context)

## Conventions

- No venv — use conda env `scribe` (see `environment.yml`)
- All config in `config.yaml`, API keys in `.env`
- Prompts in `prompts.json`, not hardcoded in Python — edit freely
- Raw transcripts always saved alongside notes for reprocessing
- Debug `print()` calls go to stderr, stdout is reserved for clean output (menu bar app reads stdout)
- Architecture decisions go in `docs/adr/NNN-slug.md`
- Improvements/bottlenecks tracked in `docs/IMPROVEMENTS.md`
- Each transcription engine is a standalone function in `src/transcriber.py`, dispatched by name
