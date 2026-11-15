import wave
from array import array
from pathlib import Path

from gameboy.__main__ import write_wav

SAMPLES = array("h", [0, 8000, -8000, 6933])


def test_write_wav_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "out.wav"

    write_wav(path, SAMPLES)

    with wave.open(str(path), "rb") as sound_file:
        assert sound_file.getnchannels() == 1
        assert sound_file.getsampwidth() == 2
        assert sound_file.getframerate() == 48000
        assert sound_file.getnframes() == len(SAMPLES)
        assert sound_file.readframes(len(SAMPLES)) == SAMPLES.tobytes()
