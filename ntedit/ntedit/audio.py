"""Real-time playback: py65 runs the play routine, reSID makes the samples."""
from __future__ import annotations

import queue
import threading
from typing import Callable, Optional

import numpy as np

from .emu import SAMPLE_RATE, SidSynth, song_player
from .model import Song


class AudioError(RuntimeError):
    pass


class LivePlayer:
    """Plays a song from the beginning of a subtune until stop() is called."""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.frame = 0                       # frames played so far (approximate)
        self.error: Optional[str] = None

    @property
    def playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, song: Song, subtune: int = 0, model_6581: bool = True,
              on_error: Optional[Callable[[str], None]] = None) -> None:
        self.stop()
        try:
            import sounddevice  # noqa: F401
        except Exception as e:                       # PortAudio missing
            raise AudioError(f"audio output unavailable: {e}")
        player = song_player(song)                   # may raise on bad song
        self._stop.clear()
        self.error = None
        self.frame = 0
        self._thread = threading.Thread(
            target=self._run, args=(player, subtune, model_6581, on_error), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self, player, subtune, model_6581, on_error):
        import sounddevice as sd
        q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=6)
        pending = np.zeros(0, dtype=np.int16)
        lock = threading.Lock()

        def callback(outdata, nframes, time, status):
            nonlocal pending
            with lock:
                while len(pending) < nframes:
                    try:
                        pending = np.concatenate([pending, q.get_nowait()])
                    except queue.Empty:
                        break
                n = min(nframes, len(pending))
                outdata[:n, 0] = pending[:n]
                outdata[n:, 0] = 0
                pending = pending[n:]

        try:
            synth = SidSynth(model_6581)
            stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                     callback=callback, blocksize=1024)
            stream.start()
        except Exception as e:
            self.error = f"audio output failed: {e}"
            if on_error:
                on_error(self.error)
            return
        try:
            writes = player.init(subtune)
            while not self._stop.is_set():
                chunk = synth.render_frame(writes)
                while not self._stop.is_set():
                    try:
                        q.put(chunk, timeout=0.05)
                        break
                    except queue.Full:
                        continue
                self.frame += 1
                writes = player.frame()
        except Exception as e:                       # emulation problem
            self.error = str(e)
            if on_error:
                on_error(self.error)
        finally:
            stream.stop()
            stream.close()
