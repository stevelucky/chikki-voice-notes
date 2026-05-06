"""CLI for Chikki — voice recording, transcription, and meeting notes."""

import os
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
    except Exception:
        # If compression fails, keep the WAV
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
            click.echo(f"\r  {_SPINNER[i % len(_SPINNER)]} {label}  {m:02d}:{s:02d}", nl=False)
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
        click.echo(f"\r  ✓ {label}  {m:02d}:{s:02d}  ({elapsed:.1f}s)")


@click.group()
def cli():
    """Chikki - Voice recording, transcription, and meeting notes."""
    pass


@cli.command()
@click.option("--duration", "-d", type=int, default=0, help="Max recording duration in seconds (0=unlimited)")
def record(duration):
    """Record audio from microphone. Press Ctrl+C to stop."""
    from .recorder import Recorder

    rec = Recorder()
    rec.start()
    click.echo(click.style("Recording... ", fg="red", bold=True) + "Press Ctrl+C to stop.")

    start = time.time()
    stopped = threading.Event()

    def handle_stop(sig, frame):
        stopped.set()

    old_handler = signal.signal(signal.SIGINT, handle_stop)

    try:
        while not stopped.is_set():
            elapsed = int(time.time() - start)
            m, s = divmod(elapsed, 60)
            click.echo(f"\r  {m:02d}:{s:02d}", nl=False)
            if duration and elapsed >= duration:
                break
            stopped.wait(0.5)
    finally:
        signal.signal(signal.SIGINT, old_handler)

    click.echo()
    filepath = rec.stop()
    if filepath:
        click.echo(click.style(f"Saved: {filepath}", fg="green"))
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

    def stage(name, detail=""):
        print(_json.dumps({"stage": name, "detail": detail}), file=_sys.stderr, flush=True)

    from .transcriber import Transcriber
    from .processor import Processor
    from .output import write_note, format_slack_message

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
        from .diarizer import Diarizer, merge_diarization
        with live_timer("Diarizing speakers"):
            d = Diarizer()
            speaker_segments = d.diarize(audio_path)
            transcript = merge_diarization(transcript, speaker_segments)

    p = Processor(meeting_type=meeting_type)
    stage("processing")
    with live_timer(f"Extracting notes ({p.type_name}) via {CONFIG['processing']['model']}"):
        processed = p.process(transcript["text"], context=context)

    stage("saving")
    with live_timer("Saving note + compressing audio"):
        note_path = write_note(processed, transcript, audio_path, audio_dur)
        _compress_audio(audio_path)

    stage("done")
    title = processed.get('title', 'N/A')
    summary = processed.get('summary', 'N/A')
    click.echo(click.style(f"\nTitle: {title}", fg="cyan", bold=True))
    click.echo(f"Summary: {summary}")

    action_items = processed.get("action_items", [])
    if action_items:
        click.echo(click.style(f"\nAction Items ({len(action_items)}):", fg="yellow"))
        for item in action_items:
            click.echo(f"  - [{item.get('owner', '?')}] {item.get('task', '')}")

    click.echo(click.style(f"\nNote saved: {note_path}", fg="green"))
    # Print summary to stdout for the menu bar app to capture
    print(summary)

    if slack:
        msg = format_slack_message(processed, note_path)
        click.echo(f"\nSlack message:\n{msg}")


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

    def handle_stop(sig, frame):
        stopped.set()

    old_handler = signal.signal(signal.SIGINT, handle_stop)

    try:
        while not stopped.is_set():
            elapsed = int(time.time() - start)
            m, s = divmod(elapsed, 60)
            click.echo(f"\r  {m:02d}:{s:02d}", nl=False)
            if duration and elapsed >= duration:
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
        from .diarizer import Diarizer, merge_diarization
        with live_timer("Diarizing speakers"):
            d = Diarizer()
            speaker_segments = d.diarize(audio_path)
            transcript = merge_diarization(transcript, speaker_segments)

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

    def stage(name, detail=""):
        """Emit a stage marker to stderr for the menu bar app to read."""
        click.echo(_json.dumps({"stage": name, "detail": detail, "t": time.time()}), err=True)

    recordings_dir = CONFIG["recording"]["recordings_dir"]
    if not os.path.exists(recordings_dir):
        click.echo("No recordings found.")
        return

    wavs = sorted(
        [f for f in os.listdir(recordings_dir) if f.endswith(".wav")],
        reverse=True,
    )
    if not wavs:
        click.echo("No recordings found.")
        return

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
        from .diarizer import Diarizer, merge_diarization
        d = Diarizer()
        speaker_segments = d.diarize(audio_path)
        transcript = merge_diarization(transcript, speaker_segments)
        
    t1 = time.time()

    stage("processing", f"Transcribed in {t1 - t0:.1f}s — sending to LLM")

    p = Processor()
    processed = p.process(transcript["text"])
    t2 = time.time()

    stage("saving", f"LLM took {t2 - t1:.1f}s")

    note_path = write_note(processed, transcript, audio_path, info.duration)
    _compress_audio(audio_path)

    title = processed.get("title", "Untitled")
    action_count = len(processed.get("action_items", []))
    total = time.time() - t0

    stage("done", f"Total: {total:.1f}s")
    print(processed.get("summary", title))


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


if __name__ == "__main__":
    cli()
