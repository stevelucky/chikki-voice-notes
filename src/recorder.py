"""Audio recorder using sounddevice. Records from default mic to WAV files.

Writes audio incrementally to disk so data is never lost on crash/force-kill.
"""

import atexit
import os
import subprocess
import queue
import threading
import time
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf

from .config import CONFIG


class Recorder:
    def __init__(self, output_path: str = None):
        self._cfg = CONFIG["recording"]
        self._sample_rate = self._cfg["sample_rate"]
        self._channels = self._cfg["channels"]
        self._max_duration = self._cfg["max_duration_minutes"] * 60
        self._recordings_dir = self._cfg["recordings_dir"]
        self._output_path = output_path  # override output file if set
        os.makedirs(self._recordings_dir, exist_ok=True)

        self._stream = None
        self._recording = False
        self._start_time = None
        self._lock = threading.Lock()
        self._file = None
        self._filepath = None
        self._caffeinate = None
        self._write_queue = None
        self._writer_thread = None
        self._stop_writer = threading.Event()

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
        # Writes happen on self._writer_loop on a dedicated Python thread.
        if status:
            print(f"[recorder] {status}")
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
                print(f"[recorder] writer error: {e}")
            finally:
                self._write_queue.task_done()

    def start(self):
        with self._lock:
            if self._recording:
                return None

            # Open WAV file for incremental writing
            if self._output_path:
                self._filepath = self._output_path
                os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
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

            # Start the writer thread before the audio stream so the queue
            # is being drained from frame 1.
            self._write_queue = queue.Queue()
            self._stop_writer.clear()
            self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
            self._writer_thread.start()

            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
            self._recording = True
            self._start_time = time.time()

            # Prevent macOS from sleeping while recording
            try:
                self._caffeinate = subprocess.Popen(
                    ["caffeinate", "-dimsu"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                self._caffeinate = None

            # Ensure we save on unexpected exit
            atexit.register(self._emergency_save)

        return True

    def stop(self):
        with self._lock:
            if not self._recording:
                return None
            self._recording = False
            # Stop the audio stream first. Callback now does no I/O so this
            # returns quickly without GIL contention.
            self._stream.stop()
            self._stream.close()
            self._stream = None

            filepath = self._filepath
            duration = time.time() - self._start_time if self._start_time else 0
            self._start_time = None

            # Drain the writer thread before closing the file.
            self._stop_writer.set()
            if self._writer_thread is not None:
                self._writer_thread.join(timeout=10)
                self._writer_thread = None
            self._write_queue = None

            if self._file is not None:
                self._file.close()
                self._file = None

            if self._caffeinate is not None:
                try:
                    self._caffeinate.terminate()
                    self._caffeinate.wait(timeout=2)
                except Exception:
                    try:
                        self._caffeinate.kill()
                    except Exception:
                        pass
                self._caffeinate = None

            try:
                atexit.unregister(self._emergency_save)
            except Exception:
                pass

        if filepath and os.path.exists(filepath):
            size = os.path.getsize(filepath)
            if size > 44:  # WAV header is 44 bytes; empty file means no audio
                print(f"[recorder] Saved: {filepath} ({duration:.1f}s)")
                return filepath
            else:
                os.remove(filepath)
                return None
        return None

    def _emergency_save(self):
        """Called by atexit — close the file so whatever was written is valid."""
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
            if self._file is not None:
                self._file.close()
                self._file = None
                print(f"\n[recorder] Emergency save: {self._filepath}")
            if self._caffeinate is not None:
                try:
                    self._caffeinate.terminate()
                except Exception:
                    pass
                self._caffeinate = None
        except Exception:
            pass

    def toggle(self):
        """Toggle recording on/off. Returns filepath when stopping, True when starting."""
        if self._recording:
            return self.stop()
        else:
            return self.start()
