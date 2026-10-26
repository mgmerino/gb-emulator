"""How is a sound wave generated from numbers?"""

import argparse
import wave
from array import array
from pathlib import Path
from typing import Final

SAMPLE_RATE: Final = 48_000
WAVE_PEAK: Final = 8_000
DUTY_PATTERNS: Final[tuple[tuple[int, ...], ...]] = (
    (0, 0, 0, 0, 0, 0, 0, 1),  # 12.5% _______-
    (1, 0, 0, 0, 0, 0, 0, 1),  # 25%   -______-
    (1, 0, 0, 0, 0, 1, 1, 1),  # 50%   -____---
    (0, 1, 1, 1, 1, 1, 1, 0),  # 75%   _------_
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
        help="select between 4 types of duty patterns",
    )
    args = parser.parse_args()
    count: int = round(args.seconds * SAMPLE_RATE)
    samples = square(frequency=args.frequency, count=count, duty=args.duty)
    write_wav(path=args.output, samples=samples)

    return 0


def square(frequency: float, count: int, duty: int = 2) -> list[int]:
    samples: list[int] = []

    for i in range(count):
        t = i / SAMPLE_RATE
        phase = (t * frequency) % 1.0
        step = int(phase * 8)
        level = DUTY_PATTERNS[duty][step]
        if level:
            sample = WAVE_PEAK
        else:
            sample = -WAVE_PEAK
        samples.append(sample)

    return samples


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
