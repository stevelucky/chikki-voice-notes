"""macOS menu bar app for Scribe voice recording.

Shows a mic icon in the menu bar. Click or use hotkey to toggle recording.
When recording stops, automatically transcribes and processes the audio.
"""

import os
import threading
import time

import rumps

from .recorder import Recorder
from .transcriber import Transcriber
from .processor import Processor
from .output import write_note, format_slack_message
from .config import CONFIG


class ScribeMenuBar(rumps.App):
    def __init__(self):
        super().__init__("Scribe", icon=None, title="🎙")
        self.recorder = Recorder()
        self.transcriber = Transcriber()
        self.processor = Processor()

        self._timer_thread = None
        self._recording_start = None

        self.menu = [
            rumps.MenuItem("Start Recording", callback=self._toggle_recording),
            None,  # separator
            rumps.MenuItem("Open Notes Folder", callback=self._open_notes),
            rumps.MenuItem("Open Recordings Folder", callback=self._open_recordings),
            None,
            rumps.MenuItem("Settings...", callback=self._show_settings),
        ]

        # Periodic timer to refresh the elapsed-time display while recording.
        self._timer = rumps.Timer(self._update_timer, 1)
        self._timer.start()

    def _toggle_recording(self, sender=None):
        if self.recorder.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        self.recorder.start()
        self.title = "🔴"
        self._recording_start = time.time()
        self.menu["Start Recording"].title = "Stop Recording"
        if CONFIG.get("menubar", {}).get("sound_on_start", True):
            os.system("afplay /System/Library/Sounds/Tink.aiff &")
        rumps.notification(
            title="Scribe",
            subtitle="Recording started",
            message="Click the menu bar icon or use hotkey to stop.",
        )

    def _stop_recording(self):
        audio_path = self.recorder.stop()
        duration = time.time() - self._recording_start if self._recording_start else 0
        self.title = "🎙"
        self._recording_start = None
        self.menu["Start Recording"].title = "Start Recording"

        if CONFIG.get("menubar", {}).get("sound_on_stop", True):
            os.system("afplay /System/Library/Sounds/Glass.aiff &")

        if audio_path:
            rumps.notification(
                title="Scribe",
                subtitle="Recording saved",
                message="Transcribing and processing...",
            )
            # Process in background thread
            threading.Thread(
                target=self._process_recording,
                args=(audio_path, duration),
                daemon=True,
            ).start()

    def _process_recording(self, audio_path: str, duration: float):
        try:
            transcript = self.transcriber.transcribe(audio_path)
            processed = self.processor.process(transcript["text"])
            note_path = write_note(processed, transcript, audio_path, duration)
            title = processed.get("title", "Voice Note")
            action_count = len(processed.get("action_items", []))
            subtitle = f"{action_count} action items" if action_count else "Processed"

            rumps.notification(
                title=f"Scribe: {title}",
                subtitle=subtitle,
                message=f"Note saved to {os.path.basename(note_path)}",
            )
        except Exception as e:
            rumps.notification(
                title="Scribe: Error",
                subtitle="Processing failed",
                message=str(e)[:100],
            )
            print(f"[menubar] Error processing: {e}")

    def _update_timer(self, _):
        if self.recorder.is_recording and self._recording_start:
            elapsed = int(time.time() - self._recording_start)
            m, s = divmod(elapsed, 60)
            self.title = f"🔴 {m:02d}:{s:02d}"

    def _open_notes(self, _):
        notes_dir = CONFIG["output"]["notes_dir"]
        os.makedirs(notes_dir, exist_ok=True)
        os.system(f'open "{notes_dir}"')

    def _open_recordings(self, _):
        rec_dir = CONFIG["recording"]["recordings_dir"]
        os.makedirs(rec_dir, exist_ok=True)
        os.system(f'open "{rec_dir}"')

    def _show_settings(self, _):
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
        os.system(f'open "{config_path}"')


def run():
    ScribeMenuBar().run()


if __name__ == "__main__":
    run()
