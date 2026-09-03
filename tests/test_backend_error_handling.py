"""
Tests for Issue #32: consistent error-handling / sentinel convention across
backends.

Convention for ``AudioBackend.read()``:
    - ``None``       -> no usable data right now (nothing available, or a chunk
                        was logged-and-skipped because conversion failed)
    - non-empty bytes -> a real audio chunk
    - ``b''`` is never used to signal an error.

Windows and Linux previously returned ``b''`` when format conversion raised,
overloading the empty-bytes value. They must now return ``None`` consistently.
"""

from types import SimpleNamespace
from unittest import mock

import pytest


class _RaisingConverter:
    def convert(self, data):
        raise ValueError("bad frame")


@pytest.fixture
def linux_mod():
    import proctap.backends.linux as linux_mod
    return linux_mod


def _make_fake_strategy_cls():
    class FakeStrategy:
        def __init__(self, pid, sample_rate=44100, channels=2, sample_width=2):
            pass
    return FakeStrategy


class TestLinuxReadErrorHandling:
    def _backend(self, linux_mod, monkeypatch, read_value, converter):
        monkeypatch.setattr(linux_mod, "PulseAudioStrategy", _make_fake_strategy_cls())
        b = linux_mod.LinuxBackend(pid=1, engine="pulse")
        b._is_running = True
        b._strategy = SimpleNamespace(read_audio=lambda timeout=0.1: read_value)
        b._converter = converter
        return b

    def test_conversion_error_returns_none(self, linux_mod, monkeypatch):
        b = self._backend(linux_mod, monkeypatch, b"\x00\x00", _RaisingConverter())
        assert b.read() is None

    def test_successful_conversion_returns_data(self, linux_mod, monkeypatch):
        conv = SimpleNamespace(convert=lambda data: b"converted")
        b = self._backend(linux_mod, monkeypatch, b"\x00\x00", conv)
        assert b.read() == b"converted"

    def test_no_data_returns_none(self, linux_mod, monkeypatch):
        conv = SimpleNamespace(convert=lambda data: b"x")
        b = self._backend(linux_mod, monkeypatch, None, conv)
        assert b.read() is None

    def test_not_running_returns_none(self, linux_mod, monkeypatch):
        b = self._backend(linux_mod, monkeypatch, b"\x00\x00", _RaisingConverter())
        b._is_running = False
        assert b.read() is None


class TestWindowsReadErrorHandling:
    def _backend(self, read_value, converter):
        from proctap.backends.windows import WindowsBackend

        b = WindowsBackend.__new__(WindowsBackend)
        b._pid = 1
        b._native = SimpleNamespace(read=lambda: read_value)
        b._converter = converter
        return b

    def test_conversion_error_returns_none(self):
        b = self._backend(b"\x00\x00", _RaisingConverter())
        assert b.read() is None

    def test_successful_conversion_returns_data(self):
        b = self._backend(b"\x00\x00", SimpleNamespace(convert=lambda data: b"converted"))
        assert b.read() == b"converted"

    def test_no_data_returns_falsy(self):
        # Native returns None when nothing is available; read() passes it through.
        b = self._backend(None, SimpleNamespace(convert=lambda data: b"x"))
        assert not b.read()
