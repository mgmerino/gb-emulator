"""How is a sound wave generated from numbers?"""

import argparse
import wave
from array import array
from pathlib import Path
from typing import Final

SAMPLE_RATE: Final = 48_000
WAVE_PEAK: Final = 8_000


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a square wave to a WAV file.")
    parser.add_argument("output", type=Path, help="where to write the WAV file")
    parser.add_argument(
        "--frequency", type=float, default=440.0, help="frequency of the tone, in Hz"
    )
    parser.add_argument(
        "--seconds", type=float, default=1.0, help="length of the tone, in seconds"
    )
    args = parser.parse_args()
    count: int = round(args.seconds * SAMPLE_RATE)
    samples = square(frequency=args.frequency, count=count)
    write_wav(path=args.output, samples=samples)

    return 0


def square(frequency: float, count: int) -> list[int]:
    samples: list[int] = []

    for i in range(count):
        t = i / SAMPLE_RATE
        phase = (t * frequency) % 1.0
        if phase < 0.5:
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
