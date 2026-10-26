"""How is a sound wave generated from numbers?"""

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
