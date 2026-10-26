"""How is a sound wave generated from numbers?

Step 17A answers it outside the emulator. Every sample is computed with plain
arithmetic and written to a 16-bit mono WAV at 48000 Hz, using only the
standard library. Each piece is one the DMG's pulse channels have: the four
8-step duty patterns, a 4-bit volume, the 64 Hz envelope, pitch written as an
11-bit period value, and the mixer. Step 17B moves them into the core, clocked
by the CPU instead of by a sample index.

Run with:

    uv run python experiments/square_wave.py /tmp/la.wav
    uv run python experiments/square_wave.py /tmp/blip.wav --duty 0 --pace 1
    uv run python experiments/square_wave.py /tmp/two.wav --melody --bass --duty 1 --pace 2

and listen with `pw-play`, starting with the system volume low.

Sample run (Python 3.12.13):

    wrote /tmp/la.wav   48000 samples   1.00 s at 48000 Hz   peak 8000
    wrote /tmp/blip.wav   48000 samples   1.00 s at 48000 Hz   peak 8000
    wrote /tmp/two.wav   48000 samples   1.00 s at 48000 Hz   peak 16000

Things it showed:

1. A sample's index is the time, and its value is where the speaker cone is at
   that time: `samples[i]` is the wave evaluated at `t = i / SAMPLE_RATE`. The
   phase is computed from `i` for every sample rather than accumulated, so a
   long tone does not drift.
2. Duty 1 (25%) and duty 3 (75%) sound the same. One is the other with every
   sample negated, and an inverted wave has the same harmonics at the same
   strengths. Two of them at the same pitch and phase cancel to silence.
3. The envelope steps are equal in amplitude but not to the ear, which hears
   ratios. 15 to 14 is -0.6 dB and 2 to 1 is -6 dB, so a slow fade seems to
   hold and then drop at the end.
4. 131072 in the pitch formula is `CLOCK_HZ // 4 // DUTY_STEPS`. The period
   value is an integer, so high notes land further from the pitch they aim at:
   C5 is 3.4 cents sharp, C8 17.
5. Mixing is adding. Each voice peaks at 8000 so that two of them fit in 16
   bits. A sum that does not fit raises `OverflowError` instead of being
   clamped, on purpose: see `mix`.
"""

import argparse
import wave
from array import array
from pathlib import Path
from typing import Final, NamedTuple

SAMPLE_RATE: Final = 48_000
WAVE_PEAK: Final = 8_000
ENVELOPE_HZ: Final = 64
TICK_SAMPLES: Final = SAMPLE_RATE // ENVELOPE_HZ
MAX_VOLUME: Final = 15
DUTY_STEPS: Final = 8
DUTY_PATTERNS: Final[tuple[tuple[int, ...], ...]] = (
    (0, 0, 0, 0, 0, 0, 0, 1),  # 12.5% _______-
    (1, 0, 0, 0, 0, 0, 0, 1),  # 25%   -______-
    (1, 0, 0, 0, 0, 1, 1, 1),  # 50%   -____---
    (0, 1, 1, 1, 1, 1, 1, 0),  # 75%   _------_
)
CLOCK_HZ: Final = 4_194_304
PULSE_HZ: Final = CLOCK_HZ // 4 // DUTY_STEPS


class Note(NamedTuple):
    period: int
    length: int


# Each period value is the integer closest to `2048 - PULSE_HZ / frequency`
MELODY: Final[tuple[Note, ...]] = (
    Note(period=1547, length=12000),  # C4 261.62 Hz
    Note(period=1650, length=12000),  # E4 329.33 Hz
    Note(period=1714, length=12000),  # G4 392.43 Hz
    Note(period=1798, length=12000),  # C5 524.29 Hz
)

BASS: Final[tuple[Note, ...]] = (
    Note(period=1046, length=24000),  # C3 130.81 Hz
    Note(period=1379, length=24000),  # G3 195.92 Hz
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a square wave to a WAV file.")
    parser.add_argument("output", type=Path, help="where to write the WAV file")
    parser.add_argument(
        "--frequency", type=float, default=440.0, help="frequency of the tone, in Hz"
    )
    parser.add_argument(
        "--seconds", type=float, default=1.0, help="length of the tone, in seconds"
    )
    parser.add_argument(
        "--duty",
        type=int,
        default=2,
        choices=range(4),
        help="DMG duty pattern, 0 to 3",
    )
    parser.add_argument(
        "--volume",
        type=int,
        default=15,
        choices=range(16),
        help="initial volume, 0 to 15",
    )
    parser.add_argument(
        "--pace",
        type=int,
        default=0,
        choices=range(8),
        help="envelope ticks per volume step, 0 to 7; 0 holds the volume",
    )
    parser.add_argument(
        "--increase",
        action="store_true",
        help="make the envelope go up instead of down",
    )
    parser.add_argument(
        "--melody",
        action="store_true",
        help="play the built-in melody instead of a single tone",
    )
    parser.add_argument(
        "--bass",
        action="store_true",
        help="mix a bass voice under the melody; needs --melody",
    )
    parser.add_argument(
        "--bass-duty",
        type=int,
        default=2,
        choices=range(4),
        help="DMG duty pattern of the bass, 0 to 3",
    )

    args = parser.parse_args()
    if args.bass and not args.melody:
        parser.error("--bass needs --melody")

    if args.melody:
        samples = build_melody(
            notes=MELODY,
            duty=args.duty,
            initial_volume=args.volume,
            increase=args.increase,
            pace=args.pace,
        )
        # The bass shares the melody's envelope and differs only in its duty
        if args.bass:
            bass = build_melody(
                notes=BASS,
                duty=args.bass_duty,
                initial_volume=args.volume,
                increase=args.increase,
                pace=args.pace,
            )
            samples = mix(samples, bass)
    else:
        count: int = round(args.seconds * SAMPLE_RATE)
        samples = square(
            frequency=args.frequency,
            count=count,
            duty=args.duty,
            initial_volume=args.volume,
            increase=args.increase,
            pace=args.pace,
        )

    write_wav(path=args.output, samples=samples)

    seconds = len(samples) / SAMPLE_RATE
    peak = max(abs(sample) for sample in samples)
    print(
        f"wrote {args.output}   {len(samples)} samples   "
        f"{seconds:.2f} s at {SAMPLE_RATE} Hz   peak {peak}"
    )

    return 0


def square(
    frequency: float,
    count: int,
    duty: int = 2,
    initial_volume: int = 15,
    increase: bool = False,
    pace: int = 0,
) -> list[int]:
    samples: list[int] = []

    for i in range(count):
        t = i / SAMPLE_RATE
        phase = (t * frequency) % 1.0
        step = int(phase * DUTY_STEPS)
        level = DUTY_PATTERNS[duty][step]
        volume = volume_at(i, initial_volume, increase, pace)
        magnitude = round(WAVE_PEAK * volume / MAX_VOLUME)

        if level:
            sample = magnitude
        else:
            sample = -magnitude

        samples.append(sample)

    return samples


def volume_at(i: int, start: int, increase: bool, pace: int) -> int:
    if pace == 0:
        return start

    elapsed_ticks = i // TICK_SAMPLES
    offset = elapsed_ticks // pace
    if increase:
        volume = start + offset
    else:
        volume = start - offset

    return min(max(volume, 0), MAX_VOLUME)


def period_to_hz(period: int) -> float:
    step_ticks = 2048 - period
    frequency = PULSE_HZ / step_ticks

    return frequency


def build_melody(
    notes: tuple[Note, ...], duty: int, initial_volume: int, increase: bool, pace: int
) -> list[int]:
    melody: list[int] = []

    for note in notes:
        frequency = period_to_hz(note.period)
        sound_wave = square(
            frequency=frequency,
            count=note.length,
            duty=duty,
            initial_volume=initial_volume,
            increase=increase,
            pace=pace,
        )
        melody.extend(sound_wave)

    return melody


def mix(*voices: list[int]) -> list[int]:
    # Neither mismatch is fixed quietly. Voices of different lengths raise here,
    # through `strict`. A sum past 16 bits is left as it is, and `array("h")`
    # raises `OverflowError` in `write_wav`, leaving a 44-byte WAV with no
    # samples. A mix that does not fit means the peaks were chosen wrong.
    # Clamping would hide that, and for square waves at equal volumes it would
    # only scale the wave down.
    return [sum(samples) for samples in zip(*voices, strict=True)]


def write_wav(path: Path, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as sound_file:
        sound_file.setnchannels(1)  # mono
        sound_file.setsampwidth(2)  # 2 bytes per sample, 16 bits
        sound_file.setframerate(SAMPLE_RATE)

        # "h" is a signed 16-bit integer. `tobytes` writes it in the machine's
        # byte order, which is little-endian on x86, the order WAV expects.
        frames = array("h", samples).tobytes()
        sound_file.writeframes(frames)


if __name__ == "__main__":
    raise SystemExit(main())
