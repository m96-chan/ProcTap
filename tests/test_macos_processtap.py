"""
Tests for the macOS Process Tap backend selection/availability (#57).

These are platform-safe: the actual capture path needs macOS 14.4+, the signed
helper app and Screen Recording permission, so it is only smoke-checked here.
"""

import platform

import pytest

from proctap.backends import macos_processtap as mpt


class TestAvailability:
    def test_not_available_off_macos(self):
        if platform.system() == "Darwin":
            pytest.skip("macOS-specific negative test")
        assert mpt.is_available() is False

    def test_find_app_returns_path_or_none(self):
        # Never raises; returns a Path to a .app or None.
        result = mpt.find_processtap_app()
        assert result is None or result.name.endswith(".app")


class TestTapConstants:
    def test_tap_native_format(self):
        # The helper negotiates 44.1kHz/2ch/float32; the backend converts to std.
        assert mpt.TAP_SAMPLE_RATE == 44100
        assert mpt.TAP_CHANNELS == 2
        assert mpt.TAP_SAMPLE_WIDTH == 4


@pytest.mark.skipif(not mpt.is_available(), reason="requires built helper on macOS")
class TestBackendConstruction:
    def test_get_format_is_standard(self):
        b = mpt.ProcessTapBackend(pid=1)
        fmt = b.get_format()
        assert fmt["sample_rate"] == 48000
        assert fmt["channels"] == 2
        assert fmt["bits_per_sample"] == 32
        assert fmt["sample_format"] == "float32"
