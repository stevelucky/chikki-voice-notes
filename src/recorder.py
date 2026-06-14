"""Audio recorder using sounddevice. Records from default mic to WAV files.

Writes audio incrementally to disk so data is never lost on crash/force-kill.
Monitors for default input device changes and seamlessly switches mid-recording.
"""

import atexit
import os
import queue
import sys
import threading
import time
from datetime import datetime

import sounddevice as sd
import soundfile as sf

from .config import CONFIG


def _default_input_name() -> str | None:
    """Return the name of the current default input device, or None."""
    try:
        idx = sd.default.device[0]
        if idx < 0:
            return None
        return sd.query_devices(idx)["name"]
    except Exception:
        return None


def _open_stream(sample_rate, channels, callback):
    stream = sd.InputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype="float32",
        callback=callback,
    )
    stream.start()
    return stream


class Recorder:
    def __init__(self, output_path: str = None):
        self._cfg = CONFIG["recording"]
        self._sample_rate = self._cfg["sample_rate"]
        self._channels = self._cfg["channels"]
        self._max_duration = self._cfg["max_duration_minutes"] * 60
        self._recordings_dir = self._cfg["recordings_dir"]
        self._output_path = output_path
        os.makedirs(self._recordings_dir, exist_ok=True)

        self._stream = None
        self._stream_lock = threading.Lock()
        self._recording = False
        self._start_time = None
        self._lock = threading.Lock()
        self._file = None
        self._filepath = None
        self._write_queue = None
        self._writer_thread = None
        self._stop_writer = threading.Event()
        self._monitor_thread = None
        self._stop_monitor = threading.Event()

    @property
    def is_recording(self):
        return self._recording

    @property
    def elapsed(self):
        if self._start_time and self._recording:
            return time.time() - self._start_time
        return 0.0

    @property
    def filepath(self):
        return self._filepath

    def _callback(self, indata, frames, time_info, status):
        # Audio thread: enqueue only, never block on disk I/O.
        if status:
            print(f"[recorder] {status}", file=sys.stderr)
        if self._write_queue is not None:
            self._write_queue.put(indata.copy())

    def _writer_loop(self):
        while True:
            try:
                chunk = self._write_queue.get(timeout=0.1)
            except queue.Empty:
                if self._stop_writer.is_set():
                    break
                continue
            try:
                if self._file is not None:
                    self._file.write(chunk)
            except Exception as e:
                print(f"[recorder] writer error: {e}", file=sys.stderr)
            finally:
                self._write_queue.task_done()

    def _device_monitor_loop(self):
        """Poll for default input device changes and restart the stream if needed."""
        current_device = _default_input_name()
        while not self._stop_monitor.wait(timeout=2.0):
            new_device = _default_input_name()
            if new_device and new_device != current_device:
                print(
                    f"[recorder] Input device changed: {current_device!r} → {new_device!r}",
                    file=sys.stderr,
                )
                current_device = new_device
                self._switch_stream()

    def _switch_stream(self):
        """Replace the active audio stream with a new one on the current default device.

        Stop the old stream *before* starting the new one so the two callbacks
        can't both enqueue audio at once (which would interleave/duplicate frames
        in the WAV). A brief gap during the switch is preferable to garbled audio.
        """
        with self._stream_lock:
            old = self._stream
            self._stream = None
            if old is not None:
                try:
                    old.stop()
                    old.close()
                except Exception:
                    pass
            try:
                self._stream = _open_stream(self._sample_rate, self._channels, self._callback)
            except Exception as e:
                print(f"[recorder] Failed to open new stream: {e}", file=sys.stderr)

    def start(self):
        with self._lock:
            if self._recording:
                return None

            if self._output_path:
                self._filepath = self._output_path
                parent = os.path.dirname(self._filepath)
                if parent:
                    os.makedirs(parent, exist_ok=True)
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"recording_{timestamp}.wav"
                self._filepath = os.path.join(self._recordings_dir, filename)
            self._file = sf.SoundFile(
                self._filepath,
                mode="w",
                samplerate=self._sample_rate,
                channels=self._channels,
                format="WAV",
                subtype="FLOAT",
            )

            # Writer thread starts before audio stream so queue is drained from frame 1.
            self._write_queue = queue.Queue()
            self._stop_writer.clear()
            self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
            self._writer_thread.start()

            with self._stream_lock:
                self._stream = _open_stream(self._sample_rate, self._channels, self._callback)
            self._recording = True
            self._start_time = time.time()

            # Watch for input device changes (e.g. AirPods removed mid-meeting).
            self._stop_monitor.clear()
            self._monitor_thread = threading.Thread(target=self._device_monitor_loop, daemon=True)
            self._monitor_thread.start()

            atexit.register(self._emergency_save)

        return True

    def stop(self):
        with self._lock:
            if not self._recording:
                return None
            self._recording = False

            # Stop device monitor first.
            self._stop_monitor.set()
            if self._monitor_thread is not None:
                self._monitor_thread.join(timeout=5)
                self._monitor_thread = None

            with self._stream_lock:
                stream = self._stream
                self._stream = None
            if stream is not None:
                stream.stop()
                stream.close()

            filepath = self._filepath
            duration = time.time() - self._start_time if self._start_time else 0
            self._start_time = None

            self._stop_writer.set()
            if self._writer_thread is not None:
                self._writer_thread.join(timeout=10)
                if self._writer_thread.is_alive():
                    print(
                        "[recorder] WARNING: writer thread did not drain within 10s; "
                        "trailing audio may be lost.",
                        file=sys.stderr,
                    )
                self._writer_thread = None
            self._write_queue = None

            if self._file is not None:
                self._file.close()
                self._file = None

            try:
                atexit.unregister(self._emergency_save)
            except Exception:
                pass

        if filepath and os.path.exists(filepath):
            # A header-only float WAV is ~58 bytes (fact/PEAK chunks), so a byte
            # threshold can't tell "empty" from "tiny". Check actual frames instead.
            try:
                frames = sf.info(filepath).frames
            except Exception:
                frames = os.path.getsize(filepath)  # fall back to bytes if unreadable
            if frames > 0:
                print(f"[recorder] Saved: {filepath} ({duration:.1f}s)", file=sys.stderr)
                return filepath
            else:
                os.remove(filepath)
                return None
        return None

    def _emergency_save(self):
        """Called by atexit — close the file so whatever was written is valid.

        Stop the audio stream and the writer thread before closing the file, so
        the (daemon) writer can't race close() — SoundFile is not thread-safe.
        """
        try:
            with self._stream_lock:
                stream = self._stream
                self._stream = None
            if stream is not None:
                stream.stop()
                stream.close()
            # Signal the writer to stop and give it a moment to drain.
            self._stop_writer.set()
            writer = self._writer_thread
            if writer is not None:
                writer.join(timeout=2)
            if self._file is not None:
                self._file.close()
                self._file = None
                print(f"\n[recorder] Emergency save: {self._filepath}", file=sys.stderr)
        except Exception:
            pass

    def toggle(self):
        """Toggle recording on/off. Returns filepath when stopping, True when starting."""
        if self._recording:
            return self.stop()
        else:
            return self.start()
