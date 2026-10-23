"""Run the real 6502 play routine (py65) and render its SID writes with reSID."""
from __future__ import annotations

import struct
from datetime import timedelta
from typing import Iterator, List, Optional, Tuple

import numpy as np
from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

from .model import Song
from .psid import INIT_ADDR, PLAY_ADDR, build_image

PAL_CLOCK = 985248
PAL_FRAME_CYCLES = 19656
TRAMPOLINE = 0x0300
SAMPLE_RATE = 44100

Write = Tuple[int, int]


class Player6502:
    """Executes init/play of a loaded image and records SID register writes."""

    def __init__(self, load: int, image: bytes, init=INIT_ADDR, play=PLAY_ADDR):
        self.mem = ObservableMemory()
        self.writes: List[Write] = []
        self.mem.subscribe_to_write(range(0xD400, 0xD419), self._on_write)
        self.mpu = MPU(memory=self.mem)
        for i, b in enumerate(image):
            self.mem[load + i] = b
        # trampoline: JSR <target> ; JMP self
        self.mem[TRAMPOLINE + 0] = 0x20
        self.mem[TRAMPOLINE + 3] = 0x4C
        self.mem[TRAMPOLINE + 4] = (TRAMPOLINE + 3) & 0xFF
        self.mem[TRAMPOLINE + 5] = (TRAMPOLINE + 3) >> 8
        self.init_addr, self.play_addr = init, play
        self.cycles = 0

    def _on_write(self, address, value):
        self.writes.append((address - 0xD400, value))
        return value

    def _call(self, addr: int, a: int = 0, limit: int = 200000) -> List[Write]:
        self.mem[TRAMPOLINE + 1] = addr & 0xFF
        self.mem[TRAMPOLINE + 2] = addr >> 8
        self.writes = []
        self.mpu.pc = TRAMPOLINE
        self.mpu.a, self.mpu.x, self.mpu.y = a, 0, 0
        self.mpu.sp = 0xFF
        steps = 0
        while self.mpu.pc != TRAMPOLINE + 3:
            self.mpu.step()
            steps += 1
            if steps > limit:
                raise RuntimeError("play routine did not return")
        return self.writes

    def init(self, subtune: int = 0) -> List[Write]:
        return self._call(self.init_addr, subtune)

    def frame(self) -> List[Write]:
        return self._call(self.play_addr)


class SidSynth:
    """reSID wrapper that renders frames of register writes to samples."""

    def __init__(self, model_6581: bool = True, rate: int = SAMPLE_RATE):
        from pyresidfp import SoundInterfaceDevice
        from pyresidfp._pyresidfp import ChipModel, SamplingMethod
        from pyresidfp import WritableRegister
        self._reg = WritableRegister
        self.sid = SoundInterfaceDevice(
            model=ChipModel.MOS6581 if model_6581 else ChipModel.MOS8580,
            sampling_method=SamplingMethod.DECIMATE,
            clock_frequency=PAL_CLOCK, sampling_frequency=rate)
        self.rate = rate
        self._frac = 0.0

    def render_frame(self, writes: List[Write]) -> np.ndarray:
        for reg, val in writes:
            self.sid.write_register(self._reg(reg), val)
        samples = self.sid.clock(timedelta(seconds=PAL_FRAME_CYCLES / PAL_CLOCK))
        return np.asarray(samples, dtype=np.int16)


def song_player(song: Song) -> Player6502:
    load, image = build_image(song)
    return Player6502(load, image)


def frames(song: Song, subtune: int = 0, n: Optional[int] = None) -> Iterator[List[Write]]:
    p = song_player(song)
    yield p.init(subtune)
    i = 0
    while n is None or i < n:
        yield p.frame()
        i += 1


def render(song: Song, subtune: int = 0, seconds: float = 10.0,
           model_6581: bool = True) -> np.ndarray:
    synth = SidSynth(model_6581)
    nframes = int(seconds * PAL_CLOCK / PAL_FRAME_CYCLES)
    chunks = [synth.render_frame(w) for w in frames(song, subtune, nframes)]
    return np.concatenate(chunks)


def write_wav(path, samples: np.ndarray, rate: int = SAMPLE_RATE) -> None:
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype("<i2").tobytes())
