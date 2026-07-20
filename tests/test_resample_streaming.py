"""
Tests for the 44.1kHz -> 48kHz resample path used by the streaming backends
(Linux, macOS Process Tap). The multi-channel scipy.resample_poly path used to
pre-allocate an output of size int(n*ratio), which mismatches resample_poly's
actual ceil(n*up/down) length -> a broadcast error that fell back to the noisy
FFT method. These pin the corrected behaviour.
"""

import numpy as np
import pytest

from proctap.backends.converter import AudioConverter, SampleFormat


def _converter():
    return AudioConverter(
        src_rate=44100, src_channels=2, src_width=4,
        dst_rate=48000, dst_channels=2, dst_width=4,
        src_format=SampleFormat.FLOAT32, dst_format=SampleFormat.FLOAT32,
        auto_detect_format=False,
    )


class TestResamplePolyMultiChannel:
    @pytest.mark.parametrize("frames", [441, 352, 480, 100, 1024])
    def test_no_broadcast_error_various_chunk_sizes(self, frames):
        conv = _converter()
        audio = np.zeros((frames, 2), dtype=np.float32)
        # Directly exercise the resample helper; must not raise and must return
        # a 2-channel array close to frames * 48000/44100.
        out = conv._resample(audio, 44100, 48000)
        assert out.ndim == 2 and out.shape[1] == 2
        expected = frames * 48000 / 44100
        assert abs(out.shape[0] - expected) <= 2

    @pytest.mark.parametrize("frames", [352, 383, 100, 1000])
    def test_resample_poly_used_not_fft_fallback(self, caplog, frames):
        # These chunk sizes have int(n*ratio) != ceil(n*up/down), which used to
        # cause a broadcast error and fall back to the FFT method.
        conv = _converter()
        audio = (np.random.default_rng(0).random((frames, 2)).astype(np.float32) - 0.5)
        with caplog.at_level("WARNING"):
            out = conv._resample(audio, 44100, 48000)
        assert "resample_poly failed" not in caplog.text
        assert out.shape[1] == 2

    def test_sine_preserved_through_full_convert(self):
        conv = _converter()
        t = np.arange(4410) / 44100.0
        tone = 0.5 * np.sin(2 * np.pi * 440 * t)
        stereo = np.stack([tone, tone], axis=1).astype(np.float32)
        out_bytes = conv.convert(stereo.tobytes())
        out = np.frombuffer(out_bytes, dtype=np.float32)
        # Resampled 44.1k->48k: ~4800 frames * 2ch, and the signal is preserved.
        assert out.size > 0
        assert 0.3 < float(np.abs(out).max()) <= 1.0
