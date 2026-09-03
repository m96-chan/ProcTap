"""
Tests for Issue #34: replace scattered magic numbers in the audio converter with
named constants. These pin the constant values (guarding against typos) and lock
the numeric conversion behaviour so the refactor cannot silently change output.
"""

import numpy as np
import pytest

from proctap.backends import converter as C
from proctap.backends.converter import AudioConverter, SampleFormat


class TestPcmConstants:
    def test_normalization_divisors(self):
        assert C.INT16_NORM_DIVISOR == 32768.0        # 2^15
        assert C.INT24_NORM_DIVISOR == 8388608.0      # 2^23
        assert C.INT32_NORM_DIVISOR == 2147483648.0   # 2^31

    def test_peak_values(self):
        assert C.INT16_PEAK == 32767.0                # 2^15 - 1
        assert C.INT24_PEAK == 8388607.0              # 2^23 - 1
        assert C.INT32_PEAK == 2147483647.0           # 2^31 - 1

    def test_detection_thresholds(self):
        assert C.FORMAT_DETECTION_MIN_SAMPLES == 100
        assert C.FORMAT_DETECTION_MIN_BYTES == 400
        assert C.FORMAT_DETECTION_SIGNAL_THRESHOLD == 100
        assert C.FLOAT32_DETECTION_MAX_ABS == 10.0


class TestConversionBehaviourUnchanged:
    def _int16_to_float(self):
        return AudioConverter(
            src_rate=48000, src_channels=1, src_width=2,
            dst_rate=48000, dst_channels=1, dst_width=4,
            src_format=SampleFormat.INT16, dst_format=SampleFormat.FLOAT32,
            auto_detect_format=False,
        )

    def _float_to_int16(self):
        return AudioConverter(
            src_rate=48000, src_channels=1, src_width=4,
            dst_rate=48000, dst_channels=1, dst_width=2,
            src_format=SampleFormat.FLOAT32, dst_format=SampleFormat.INT16,
            auto_detect_format=False,
        )

    def test_int16_normalization(self):
        conv = self._int16_to_float()
        pcm = np.array([32767, -32768, 0], dtype=np.int16).tobytes()
        out = np.frombuffer(conv.convert(pcm), dtype=np.float32)
        assert out[2] == 0.0
        assert out[0] == pytest.approx(32767 / 32768.0, abs=1e-6)
        assert out[1] == pytest.approx(-1.0, abs=1e-6)

    def test_float_to_int16_peak(self):
        conv = self._float_to_int16()
        pcm = np.array([1.0, -1.0, 0.0], dtype=np.float32).tobytes()
        out = np.frombuffer(conv.convert(pcm), dtype=np.int16)
        assert out[0] == 32767   # +1.0 scaled by INT16_PEAK, not 32768 (no overflow)
        assert out[1] == -32767
        assert out[2] == 0
