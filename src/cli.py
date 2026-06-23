"""CLI for Scribe — voice recording, transcription, and meeting notes."""

import os
import re
import sys
import time
import signal
import threading
from contextlib import contextmanager

import click

from .config import CONFIG

def _resolve_length(length, segments=None):
    """Map user-provided length (or audio duration) to processing strategy.
    Returns 'chunked' or 'single'.

    Default: auto-detect from audio duration. 90+ min -> chunked.
    Override: --length long forces chunked, --length short/medium forces single."""
    if length == "long":
        return "chunked"
    if length in ("short", "medium"):
        return "single"
    # length is None or "open" -> auto-decide from segments
    if segments:
        last_end = segments[-1].get("end", 0)
        if last_end >= 90 * 60:
            return "chunked"
    return "single"




_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _effective_cap_seconds(duration: int) -> int:
    """Resolve the recording cap in seconds.

    An explicit --duration always wins. Otherwise fall back to the configured
    recording.max_duration_minutes safety cap (0 = unlimited).
    """
    if duration:
        return duration
    minutes = CONFIG.get("recording", {}).get("max_duration_minutes", 0) or 0
    return int(minutes * 60)


def _audio_age_seconds(path: str) -> float:
    """Age of an audio file — by its recording timestamp in the filename when
    present (recording_YYYYMMDD_HHMMSS), else file mtime."""
    m = re.search(r"(\d{8})_(\d{6})", os.path.basename(path))
    if m:
        from datetime import datetime
        try:
            ts = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            return time.time() - ts.timestamp()
        except ValueError:
            pass
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return 0.0


def _prune_old_audio() -> int:
    """Delete recordings older than recording.retention_days. 0/absent = never."""
    import glob
    cfg = CONFIG.get("recording", {})
    days = cfg.get("retention_days", 0) or 0
    recordings_dir = cfg.get("recordings_dir")
    if not days or days <= 0 or not recordings_dir or not os.path.isdir(recordings_dir):
        return 0
    cutoff = days * 86400
    removed = 0
    for ext in ("*.wav", "*.flac", "*.mp3", "*.m4a"):
        for f in glob.glob(os.path.join(recordings_dir, ext)):
            if _audio_age_seconds(f) > cutoff:
                try:
                    os.remove(f)
                    removed += 1
                except OSError:
                    pass
    if removed:
        print(f"[retention] Deleted {removed} audio file(s) older than {days} days.", file=sys.stderr)
    return removed


def _ensure_wav(audio_path: str) -> str:
    """Return a path to a 16kHz mono WAV for any input audio.

    WAV inputs pass through unchanged. Other formats (e.g. m4a from the phone /
    Voice Memos, mp3, etc.) are transcoded into recordings/ via ffmpeg, named with
    the source file's timestamp so the note gets the right date. Returns the new
    WAV path.
    """
    import shutil
    import subprocess
    from datetime import datetime

    if audio_path.lower().endswith(".wav"):
        return audio_path
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to import non-WAV audio (brew install ffmpeg).")

    recordings_dir = CONFIG["recording"]["recordings_dir"]
    os.makedirs(recordings_dir, exist_ok=True)
    try:
        ts = datetime.fromtimestamp(os.path.getmtime(audio_path))
    except OSError:
        ts = datetime.now()
    base = f"recording_{ts.strftime('%Y%m%d_%H%M%S')}"
    out = os.path.join(recordings_dir, base + ".wav")
    n = 2
    while os.path.exists(out):
        out = os.path.join(recordings_dir, f"{base}_{n}.wav")
        n += 1

    sr = CONFIG["recording"].get("sample_rate", 16000)
    ch = CONFIG["recording"].get("channels", 1)
    print(f"[import] Transcoding {os.path.basename(audio_path)} -> {os.path.basename(out)}", file=sys.stderr)
    subprocess.run(
        ["ffmpeg", "-i", audio_path, "-ar", str(sr), "-ac", str(ch), "-y", out],
        capture_output=True, check=True,
    )
    return out


def _compress_audio(wav_path: str):
    """Compress WAV to FLAC (lossless, ~50-60% smaller). Keeps original until verified."""
    import subprocess
    import shutil

    if not wav_path.endswith(".wav") or not os.path.exists(wav_path):
        return

    flac_path = wav_path.rsplit(".", 1)[0] + ".flac"
    if os.path.exists(flac_path):
        os.remove(wav_path)  # FLAC exists but WAV wasn't cleaned up — remove it now
        return

    if not shutil.which("ffmpeg"):
        return  # ffmpeg not available

    try:
        subprocess.run(
            ["ffmpeg", "-i", wav_path, "-c:a", "flac", "-y", flac_path],
            capture_output=True, check=True,
        )
        wav_size = os.path.getsize(wav_path)
        flac_size = os.path.getsize(flac_path)
        savings = 100 * (1 - flac_size / wav_size) if wav_size > 0 else 0
        os.remove(wav_path)
        print(f"[compress] {os.path.basename(wav_path)} → .flac ({savings:.0f}% smaller)", file=sys.stderr)
    except Exception as e:
        # If compression fails, keep the WAV and surface why.
        print(f"[compress] failed for {os.path.basename(wav_path)} ({e}); keeping WAV.", file=sys.stderr)
        if os.path.exists(flac_path):
            os.remove(flac_path)


@contextmanager
def live_timer(label: str):
    """Show a spinner with elapsed time while a block runs. Yields a dict to store timing."""
    stop = threading.Event()
    start = time.time()
    result = {"elapsed": 0.0}

    def _spin():
        i = 0
        while not stop.is_set():
            elapsed = time.time() - start
            m, s = divmod(int(elapsed), 60)
            click.echo(f"\r  {_SPINNER[i % len(_SPINNER)]} {label}  {m:02d}:{s:02d}", nl=False, err=True)
            i += 1
            stop.wait(0.1)

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    try:
        yield result
    finally:
        stop.set()
        t.join()
        result["elapsed"] = time.time() - start
        elapsed = result["elapsed"]
        m, s = divmod(int(elapsed), 60)
        click.echo(f"\r  ✓ {label}  {m:02d}:{s:02d}  ({elapsed:.1f}s)", err=True)


@click.group()
def cli():
    """Scribe - Voice recording, transcription, and meeting notes."""
    pass


@cli.command()
@click.option("--duration", "-d", type=int, default=0, help="Max recording duration in seconds (0=unlimited)")
@click.option("--output", "-o", default=None, help="Override output file path")
@click.option("--meter", is_flag=True, default=False,
              help="Stream live audio levels as JSON to stdout (used by the menu bar meter)")
def record(duration, output, meter):
    """Record audio from microphone. Press Ctrl+C to stop."""
    import json as _json
    from .recorder import Recorder

    on_level = None
    if meter:
        def on_level(bands):
            # One compact JSON object per line on stdout; the menu bar parses these
            # to drive the equalizer. Swallow pipe errors if the reader goes away.
            try:
                sys.stdout.write(_json.dumps({"lvl": [round(b, 3) for b in bands]}) + "\n")
                sys.stdout.flush()
            except (BrokenPipeError, ValueError, OSError):
                pass

    rec = Recorder(output_path=output, on_level=on_level)
    rec.start()
    click.echo(click.style("Recording... ", fg="red", bold=True) + "Press Ctrl+C to stop.")

    start = time.time()
    stopped = threading.Event()
    cap = _effective_cap_seconds(duration)

    def handle_stop(sig, frame):
        stopped.set()

    old_handler = signal.signal(signal.SIGINT, handle_stop)

    try:
        while not stopped.is_set():
            elapsed = int(time.time() - start)
            m, s = divmod(elapsed, 60)
            click.echo(f"\r  {m:02d}:{s:02d}", nl=False, err=True)
            if cap and elapsed >= cap:
                click.echo(f"\n[recorder] Reached max duration ({cap}s) — stopping.", err=True)
                break
            stopped.wait(0.5)
    finally:
        signal.signal(signal.SIGINT, old_handler)

    click.echo(err=True)
    filepath = rec.stop()
    if filepath:
        click.echo(click.style(f"Saved: {filepath}", fg="green"), err=True)
    return filepath


@cli.command()
@click.argument("audio_path", type=click.Path(exists=True))
@click.option("--engine", "-e", type=click.Choice(["whisper", "indicwhisper", "parakeet"]), default=None,
              help="Transcription engine (default: from config)")
def transcribe(audio_path, engine):
    """Transcribe an audio file."""
    from .transcriber import Transcriber

    t = Transcriber(engine=engine)
    click.echo(click.style(f"Engine: {t.engine_name}", fg="blue"))
    result = t.transcribe(audio_path)
    click.echo(result["text"])


@cli.command()
@click.argument("audio_path", type=click.Path(exists=True))
@click.option("--context", "-c", default="", help="Additional context for the LLM")
@click.option("--slack/--no-slack", default=False, help="Post summary to Slack")
@click.option("--engine", "-e", type=click.Choice(["whisper", "indicwhisper", "parakeet"]), default=None,
              help="Transcription engine (default: from config)")
@click.option("--type", "-t", "meeting_type", default=None,
              help="Meeting type: default, standup, strategy, one_on_one, brainstorm, interview")
@click.option("--diarize/--no-diarize", default=None, help="Enable speaker diarization")
def process(audio_path, context, slack, engine, meeting_type, diarize):
    """Transcribe and process an audio file into structured notes."""
    import json as _json
    import sys as _sys

    def stage(name, detail="", **extra):
        print(_json.dumps({"stage": name, "detail": detail, **extra}), file=_sys.stderr, flush=True)

    from .transcriber import Transcriber
    from .processor import Processor
    from .output import write_note, format_slack_message

    # Accept non-WAV imports (m4a from the phone, etc.) by transcoding first.
    if not audio_path.lower().endswith(".wav"):
        stage("importing", "Converting audio")
        audio_path = _ensure_wav(audio_path)

    import soundfile as sf
    info = sf.info(audio_path)
    audio_dur = info.duration
    dur_str = f"{int(audio_dur // 60)}m {int(audio_dur % 60)}s"
    engine_name = engine or CONFIG["transcription"]["engine"]

    from .cleaner import clean_transcript

    t = Transcriber(engine=engine)
    stage("transcribing", f"{dur_str} audio")
    with live_timer(f"Transcribing ({engine_name}, {dur_str} audio)"):
        transcript = t.transcribe(audio_path)

    with live_timer("Cleaning transcript"):
        transcript = clean_transcript(transcript)

    do_diarize = diarize if diarize is not None else CONFIG.get("transcription", {}).get("diarization", {}).get("enabled", False)
    if do_diarize:
        from .diarizer import Diarizer, identify_and_merge
        from .config import _BASE_DIR
        stage("diarizing", "Running pyannote pipeline...")
        with live_timer("Diarizing speakers"):
            d = Diarizer()
            speaker_segments = d.diarize(audio_path)
            transcript = identify_and_merge(transcript, speaker_segments, audio_path, _BASE_DIR)

    p = Processor(meeting_type=meeting_type)
    stage("processing")
    with live_timer(f"Extracting notes ({p.type_name}) via {CONFIG['processing']['model']}"):
        processed = p.process(transcript["text"], context=context)

    stage("saving")
    with live_timer("Saving note + compressing audio"):
        note_path = write_note(processed, transcript, audio_path, audio_dur)
        _compress_audio(audio_path)
        _prune_old_audio()

    stage("done", note=os.path.basename(note_path))
    title = processed.get('title', 'N/A')
    summary = processed.get('summary', 'N/A')
    click.echo(click.style(f"\nTitle: {title}", fg="cyan", bold=True), err=True)
    click.echo(f"Summary: {summary}", err=True)

    action_items = processed.get("action_items", [])
    if action_items:
        click.echo(click.style(f"\nAction Items ({len(action_items)}):", fg="yellow"), err=True)
        for item in action_items:
            click.echo(f"  - [{item.get('owner', '?')}] {item.get('task', '')}", err=True)

    click.echo(click.style(f"\nNote saved: {note_path}", fg="green"), err=True)
    # Only the title goes to stdout — menu bar app reads this
    print(title)

    if slack:
        # stdout is reserved for the title (menu bar app reads it); send Slack
        # preview to stderr.
        msg = format_slack_message(processed, note_path)
        click.echo(f"\nSlack message:\n{msg}", err=True)


@cli.command()
@click.option("--context", "-c", default="", help="Additional context for the LLM")
@click.option("--slack/--no-slack", default=False, help="Post summary to Slack")
@click.option("--duration", "-d", type=int, default=0, help="Max duration in seconds")
@click.option("--engine", "-e", type=click.Choice(["whisper", "indicwhisper", "parakeet"]), default=None,
              help="Transcription engine (default: from config)")
@click.option("--type", "-t", "meeting_type", default=None,
              help="Meeting type: default, standup, strategy, one_on_one, brainstorm, interview")
@click.option("--length", type=click.Choice(["short","medium","long","open"]), default=None, help="Meeting length. Long enables 30-min chunked summarization.")
@click.option("--diarize/--no-diarize", default=None, help="Enable speaker diarization")
def quick(context, slack, duration, engine, meeting_type, length, diarize):
    """Record, transcribe, and process in one go. Ctrl+C to stop recording."""
    from .recorder import Recorder
    from .transcriber import Transcriber
    from .processor import Processor
    from .output import write_note, format_slack_message

    rec = Recorder()
    rec.start()
    click.echo(click.style("Recording... ", fg="red", bold=True) + "Press Ctrl+C to stop.")

    start = time.time()
    stopped = threading.Event()
    cap = _effective_cap_seconds(duration)

    def handle_stop(sig, frame):
        stopped.set()

    old_handler = signal.signal(signal.SIGINT, handle_stop)

    try:
        while not stopped.is_set():
            elapsed = int(time.time() - start)
            m, s = divmod(elapsed, 60)
            click.echo(f"\r  {m:02d}:{s:02d}", nl=False, err=True)
            if cap and elapsed >= cap:
                break
            stopped.wait(0.5)
    finally:
        # Block further Ctrl+C until post-processing completes. A second
        # Ctrl+C here would kill transcription/diarization/summary mid-flight
        # and we'd lose the meeting note even though the audio is on disk.
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    click.echo()
    click.echo(click.style("Stopping recording... (Ctrl+C disabled — processing in progress)", fg="yellow"))
    audio_path = rec.stop()
    if not audio_path:
        click.echo("No audio recorded.")
        return

    click.echo(click.style(f"Saved: {audio_path}", fg="green"))

    rec_duration = time.time() - start
    dur_str = f"{int(rec_duration // 60)}m {int(rec_duration % 60)}s"
    engine_name = engine or CONFIG["transcription"]["engine"]

    from .cleaner import clean_transcript

    t = Transcriber(engine=engine)
    with live_timer(f"Transcribing ({engine_name}, {dur_str} audio)"):
        transcript = t.transcribe(audio_path)

    with live_timer("Cleaning transcript"):
        transcript = clean_transcript(transcript)

    do_diarize = diarize if diarize is not None else CONFIG.get("transcription", {}).get("diarization", {}).get("enabled", False)
    if do_diarize:
        from .diarizer import Diarizer, identify_and_merge
        from .config import _BASE_DIR
        with live_timer("Diarizing speakers"):
            d = Diarizer()
            speaker_segments = d.diarize(audio_path)
            transcript = identify_and_merge(transcript, speaker_segments, audio_path, _BASE_DIR)

    p = Processor(meeting_type=meeting_type)
    _strategy = _resolve_length(length, transcript.get("segments"))
    _last_end = transcript.get("segments", [{}])[-1].get("end", 0) if transcript.get("segments") else 0
    click.echo(f"  [duration={_last_end/60:.1f}min, override={length or 'auto'}, strategy={_strategy}]")
    with live_timer(f"Extracting notes ({p.type_name}) via {CONFIG['processing']['model']}"):
        if _strategy == "chunked":
            processed = p.process_chunked(transcript, context=context)
        else:
            processed = p.process(transcript["text"], context=context)

    with live_timer("Saving note + compressing audio"):
        note_path = write_note(processed, transcript, audio_path, rec_duration)
        _compress_audio(audio_path)
        _prune_old_audio()

    click.echo(click.style(f"\nTitle: {processed.get('title', 'N/A')}", fg="cyan", bold=True))
    click.echo(f"Summary: {processed.get('summary', 'N/A')}")

    action_items = processed.get("action_items", [])
    if action_items:
        click.echo(click.style(f"\nAction Items ({len(action_items)}):", fg="yellow"))
        for item in action_items:
            click.echo(f"  - [{item.get('owner', '?')}] {item.get('task', '')}")

    click.echo(click.style(f"\nNote saved: {note_path}", fg="green"))


@cli.command()
def engines():
    """List available transcription engines."""
    from .transcriber import Transcriber

    active = CONFIG["transcription"]["engine"]
    for name, desc in Transcriber.available_engines().items():
        marker = click.style(" (active)", fg="green") if name == active else ""
        click.echo(f"  {click.style(name, bold=True)}{marker}")
        click.echo(f"    {desc}")
        model = CONFIG["transcription"]["engines"][name]["model"]
        click.echo(f"    Model: {model}")
        click.echo()


@cli.command()
def types():
    """List available meeting types for --type flag."""
    from .processor import available_types

    default_type = CONFIG.get("processing", {}).get("default_type", "default")
    for key, info in available_types().items():
        marker = click.style(" (default)", fg="green") if key == default_type else ""
        click.echo(f"  {click.style(key, bold=True)}{marker}")
        click.echo(f"    {info['name']} — {info['description']}")
        click.echo()


@cli.command()
@click.argument("transcript_path", type=click.Path(exists=True))
@click.option("--type", "-t", "meeting_type", required=True,
              help="Meeting type: default, standup, strategy, one_on_one, brainstorm, interview")
@click.option("--context", "-c", default="", help="Additional context for the LLM")
def reprocess(transcript_path, meeting_type, context):
    """Re-summarize a saved transcript with a different meeting type.

    Use with transcript JSON files in transcripts/ folder.
    Example: python -m src.cli reprocess transcripts/20260323_1231_my-meeting.json --type standup
    """
    import json as _json
    from .processor import Processor
    from .output import write_note

    # If given an audio file, transcribe it first then process with the requested type
    if transcript_path.endswith((".wav", ".mp3", ".m4a", ".flac", ".ogg")):
        from .transcriber import Transcriber
        click.echo(f"Audio file detected — transcribing first, then processing as {meeting_type}.")
        t = Transcriber()
        with live_timer("Transcribing audio"):
            transcript = t.transcribe(transcript_path)
    elif transcript_path.endswith(".json"):
        with open(transcript_path) as f:
            transcript = _json.load(f)
    else:
        with open(transcript_path) as f:
            transcript = {"text": f.read(), "segments": [], "language": "en"}

    text = transcript.get("text", "")
    if not text:
        click.echo("Empty transcript.")
        return

    p = Processor(meeting_type=meeting_type)
    with live_timer(f"Re-extracting ({p.type_name}) via {CONFIG['processing']['model']}"):
        processed = p.process(text, context=context)

    # Use a dummy audio path for the note
    note_path = write_note(processed, transcript, transcript_path, 0)

    click.echo(click.style(f"\nTitle: {processed.get('title', 'N/A')}", fg="cyan", bold=True))
    click.echo(f"Summary: {processed.get('summary', 'N/A')}")
    click.echo(click.style(f"\nNote saved: {note_path}", fg="green"))


@cli.command()
def menubar():
    """Launch the menu bar app."""
    from .menubar import run
    run()


@cli.command("process-latest")
@click.option("--engine", "-e", type=click.Choice(["whisper", "indicwhisper", "parakeet"]), default=None)
@click.option("--diarize/--no-diarize", default=None, help="Enable speaker diarization")
def process_latest(engine, diarize):
    """Process the most recent recording. Used by the menu bar app."""
    import json as _json
    from .transcriber import Transcriber
    from .processor import Processor
    from .output import write_note

    def stage(name, detail="", **extra):
        """Emit a stage marker to stderr for the menu bar app to read."""
        click.echo(_json.dumps({"stage": name, "detail": detail, "t": time.time(), **extra}), err=True)

    recordings_dir = CONFIG["recording"]["recordings_dir"]
    if not os.path.exists(recordings_dir):
        click.echo("No recordings found.", err=True)
        raise SystemExit(1)

    import re as _re
    # Only consider timestamped recordings (recording_YYYYMMDD_HHMMSS.wav) so a
    # stray .wav dropped into the folder can't be picked as "latest".
    _rec_re = _re.compile(r"^recording_\d{8}_\d{6}\.wav$")
    wavs = sorted(
        [f for f in os.listdir(recordings_dir) if _rec_re.match(f)],
        reverse=True,
    )
    if not wavs:
        click.echo("No recordings found.", err=True)
        raise SystemExit(1)

    audio_path = os.path.join(recordings_dir, wavs[0])

    import soundfile as sf
    info = sf.info(audio_path)
    duration_str = f"{int(info.duration // 60)}m {int(info.duration % 60)}s"
    stage("transcribing", f"{wavs[0]} ({duration_str})")

    from .cleaner import clean_transcript

    t0 = time.time()
    t = Transcriber(engine=engine)
    transcript = t.transcribe(audio_path)
    
    transcript = clean_transcript(transcript)
    
    do_diarize = diarize if diarize is not None else CONFIG.get("transcription", {}).get("diarization", {}).get("enabled", False)
    if do_diarize:
        stage("diarizing", "Running pyannote pipeline...")
        from .diarizer import Diarizer, identify_and_merge
        from .config import _BASE_DIR
        d = Diarizer()
        speaker_segments = d.diarize(audio_path)
        transcript = identify_and_merge(transcript, speaker_segments, audio_path, _BASE_DIR)
        
    t1 = time.time()

    stage("processing", f"Transcribed in {t1 - t0:.1f}s — sending to LLM")

    p = Processor()
    processed = p.process(transcript["text"])
    t2 = time.time()

    stage("saving", f"LLM took {t2 - t1:.1f}s")

    note_path = write_note(processed, transcript, audio_path, info.duration)
    _compress_audio(audio_path)
    _prune_old_audio()

    title = processed.get("title", "Untitled")
    action_count = len(processed.get("action_items", []))
    total = time.time() - t0

    stage("done", f"Total: {total:.1f}s", note=os.path.basename(note_path))
    print(title)


@cli.command("correct")
@click.option("--file", "-f", "note_file", default=None,
              help="Note filename to correct (default: the most recent note)")
@click.option("--message", "-m", required=True,
              help="Plain-English correction, e.g. \"I'm the host, not Dwight\"")
def correct(note_file, message):
    """Apply a natural-language correction to a note and regenerate it.

    Re-reads the note's original transcript with your correction as the source of
    truth, so the fix (e.g. a reversed speaker attribution) propagates throughout
    the note. Checked-off action items are preserved. Used by the menu bar app.
    """
    import json as _json
    import sys as _sys
    from .corrections import correct_note, latest_note

    def stage(name, detail="", **extra):
        print(_json.dumps({"stage": name, "detail": detail, **extra}), file=_sys.stderr, flush=True)

    target = note_file or latest_note()
    if not target:
        click.echo("No note found to correct.", err=True)
        raise SystemExit(1)

    stage("correcting", "Re-reading transcript with your correction")
    res = correct_note(target, message)
    if not res.get("ok"):
        click.echo(res.get("error", "Correction failed."), err=True)
        raise SystemExit(1)

    stage("done", note=target)
    title = res.get("title", "Untitled")
    restored = res.get("checkmarks_restored", 0)
    if restored:
        click.echo(f"Restored {restored} checked-off item(s).", err=True)
    click.echo(click.style(f"Corrected: {title}", fg="green"), err=True)
    # stdout reserved for the title (menu bar app reads it).
    print(title)


@cli.command()
def list_notes():
    """List all saved notes."""
    notes_dir = CONFIG["output"]["notes_dir"]
    if not os.path.exists(notes_dir):
        click.echo("No notes yet.")
        return

    notes = sorted(
        [f for f in os.listdir(notes_dir) if f.endswith(".md")],
        reverse=True,
    )
    if not notes:
        click.echo("No notes yet.")
        return

    for note in notes:
        filepath = os.path.join(notes_dir, note)
        # Read first few lines to get title
        with open(filepath) as f:
            lines = f.readlines()
        title = "Untitled"
        for line in lines:
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip('"')
                break
        click.echo(f"  {note}  —  {title}")


@cli.command("enroll-speaker")
@click.argument("audio_path", type=click.Path(exists=True))
@click.option("--name", "-n", required=True, help="Speaker's full name")
@click.option("--role", "-r", default="", help="Speaker's role or title")
@click.option("--notes", default="", help="Any additional notes")
def enroll_speaker(audio_path, name, role, notes):
    """Enroll a speaker from a voice sample for automatic identification."""
    from .speaker_profiles import enroll_speaker as _enroll
    from .config import _BASE_DIR
    with live_timer(f"Computing embedding for {name}"):
        profile = _enroll(_BASE_DIR, name, role, notes, audio_path)
    click.echo(click.style(f"\nEnrolled: {profile['name']}", fg="green", bold=True))
    if role:
        click.echo(f"Role: {role}")
    click.echo(f"Sample: {profile['sample']}")


@cli.command("list-speakers")
def list_speakers():
    """List all enrolled speakers."""
    from .speaker_profiles import load_profiles
    from .config import _BASE_DIR
    profiles = load_profiles(_BASE_DIR)
    if not profiles:
        click.echo("No speakers enrolled yet.")
        return
    for p in profiles:
        role_str = f"  ({p['role']})" if p.get('role') else ""
        click.echo(f"  {p['name']}{role_str}")


@cli.command("delete-speaker")
@click.argument("name")
def delete_speaker(name):
    """Remove an enrolled speaker."""
    from .speaker_profiles import delete_speaker as _delete
    from .config import _BASE_DIR
    _delete(_BASE_DIR, name)
    click.echo(click.style(f"Deleted: {name}", fg="yellow"))


@cli.command("cleanup-audio")
def cleanup_audio():
    """Delete audio files older than recording.retention_days (0 = never delete)."""
    days = CONFIG.get("recording", {}).get("retention_days", 0) or 0
    if not days or days <= 0:
        click.echo("Retention is disabled (recording.retention_days = 0). Nothing deleted.", err=True)
        return
    n = _prune_old_audio()
    click.echo(click.style(f"Deleted {n} audio file(s) older than {days} days.", fg="yellow"), err=True)


@cli.command("reprocess-all")
@click.option("--type", "-t", "force_type", default=None,
              help="Force this meeting type for all notes (default: keep each note's type)")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt")
def reprocess_all(force_type, yes):
    """Re-run extraction on every saved transcript and OVERWRITE the notes in place.

    Use after changing prompts to retroactively apply the new extraction. Each note
    is regenerated from its transcript (same filename + date), so any manual edits
    (checked-off items, reassignments) are lost.
    """
    import glob
    import json as _json
    from datetime import datetime
    from .processor import Processor
    from .output import write_note
    from .notes_index import _parse_frontmatter

    notes_dir = CONFIG["output"]["notes_dir"]
    transcripts_dir = os.path.join(os.path.dirname(notes_dir), "transcripts")
    jsons = sorted(glob.glob(os.path.join(transcripts_dir, "*.json")))
    if not jsons:
        click.echo("No transcripts found to reprocess.", err=True)
        return
    if not yes:
        click.confirm(
            f"Re-extract and OVERWRITE {len(jsons)} notes? Manual edits (checkmarks, "
            f"reassignments) will be lost.", abort=True,
        )

    processors = {}

    def _processor_for(mtype):
        p = processors.get(mtype)
        if p is None:
            try:
                p = Processor(meeting_type=mtype)
            except ValueError:
                p = processors.get("default") or Processor()
                mtype = "default"
            processors[mtype] = p
        return p

    done = 0
    skipped_orphans = 0
    for jpath in jsons:
        base = os.path.splitext(os.path.basename(jpath))[0]
        note_path = os.path.join(notes_dir, base + ".md")
        # Only reprocess transcripts that still have a live note — never resurrect
        # notes the user has deleted.
        if not os.path.exists(note_path):
            skipped_orphans += 1
            continue
        meta, _ = _parse_frontmatter(open(note_path, encoding="utf-8").read())
        mtype = force_type or str(meta.get("type") or "default")
        try:
            transcript = _json.load(open(jpath, encoding="utf-8"))
        except Exception as e:
            click.echo(f"  skip {base}: unreadable transcript ({e})", err=True)
            continue
        if not transcript.get("text", "").strip():
            click.echo(f"  skip {base}: empty transcript", err=True)
            continue

        ts = None
        m = re.match(r"(\d{8})_(\d{4})", base)
        if m:
            try:
                ts = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M")
            except ValueError:
                pass

        p = _processor_for(mtype)
        with live_timer(f"{base[:44]} ({p.type_name})"):
            processed = p.process(transcript["text"])
        write_note(processed, transcript, audio_path=str(meta.get("audio") or ""),
                   duration=meta.get("duration") or 0, base_name=base, timestamp=ts)
        done += 1

    msg = f"\nReprocessed {done} notes."
    if skipped_orphans:
        msg += f" Skipped {skipped_orphans} orphan transcript(s) with no current note."
    click.echo(click.style(msg, fg="green"), err=True)


if __name__ == "__main__":
    cli()
