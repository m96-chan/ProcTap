"""
Characterization tests for LinuxBackend engine/strategy selection (Issue #29).

The deeply-nested try/except fallback chain in ``LinuxBackend.__init__`` is being
flattened into a strategy-chain pattern. These tests pin down which strategy is
chosen for every ``engine`` value and every fallback situation so the refactor
provably preserves behaviour.

Strategy classes are replaced with light fakes so no real PulseAudio / PipeWire
is needed; the real ``AudioConverter`` (numpy) is exercised unchanged.
"""

import pytest


@pytest.fixture
def linux_mod():
    import proctap.backends.linux as linux_mod
    return linux_mod


def make_fake_strategy(label, fail=False):
    """Build a stand-in strategy class tagged with ``label``."""

    class FakeStrategy:
        strategy_label = label
        _should_fail = fail

        def __init__(self, pid, sample_rate=44100, channels=2, sample_width=2):
            if type(self)._should_fail:
                raise RuntimeError(f"{label} unavailable")
            self.pid = pid
            self.sample_rate = sample_rate
            self.channels = channels
            self.sample_width = sample_width

    FakeStrategy.__name__ = f"Fake{label}Strategy"
    return FakeStrategy


@pytest.fixture
def patch_strategies(monkeypatch, linux_mod):
    """Replace the three strategy classes; return a helper to configure failures."""

    def configure(native=False, pipewire=False, pulse=False):
        monkeypatch.setattr(
            linux_mod, "PipeWireNativeStrategy",
            make_fake_strategy("native", fail=native),
        )
        monkeypatch.setattr(
            linux_mod, "PipeWireStrategy",
            make_fake_strategy("pipewire", fail=pipewire),
        )
        monkeypatch.setattr(
            linux_mod, "PulseAudioStrategy",
            make_fake_strategy("pulse", fail=pulse),
        )

    return configure


def _label(backend):
    return backend._strategy.strategy_label


class TestExplicitEngine:
    def test_pulse(self, linux_mod, patch_strategies):
        patch_strategies()
        b = linux_mod.LinuxBackend(pid=1, engine="pulse")
        assert _label(b) == "pulse"

    def test_pipewire(self, linux_mod, patch_strategies):
        patch_strategies()
        b = linux_mod.LinuxBackend(pid=1, engine="pipewire")
        assert _label(b) == "pipewire"

    def test_pipewire_native(self, linux_mod, patch_strategies):
        patch_strategies()
        b = linux_mod.LinuxBackend(pid=1, engine="pipewire-native")
        assert _label(b) == "native"

    def test_unknown_engine_raises(self, linux_mod, patch_strategies):
        patch_strategies()
        with pytest.raises(ValueError, match="Unknown engine"):
            linux_mod.LinuxBackend(pid=1, engine="bogus")


class TestFallbackChains:
    def test_pipewire_falls_back_to_pulse(self, linux_mod, patch_strategies):
        patch_strategies(pipewire=True)
        b = linux_mod.LinuxBackend(pid=1, engine="pipewire")
        assert _label(b) == "pulse"

    def test_native_falls_back_to_pipewire(self, linux_mod, patch_strategies):
        patch_strategies(native=True)
        b = linux_mod.LinuxBackend(pid=1, engine="pipewire-native")
        assert _label(b) == "pipewire"

    def test_native_falls_back_through_to_pulse(self, linux_mod, patch_strategies):
        patch_strategies(native=True, pipewire=True)
        b = linux_mod.LinuxBackend(pid=1, engine="pipewire-native")
        assert _label(b) == "pulse"

    def test_pulse_only_has_no_fallback(self, linux_mod, patch_strategies):
        patch_strategies(pulse=True)
        with pytest.raises(RuntimeError):
            linux_mod.LinuxBackend(pid=1, engine="pulse")

    def test_all_fail_raises_runtime_error(self, linux_mod, patch_strategies):
        patch_strategies(native=True, pipewire=True, pulse=True)
        with pytest.raises(RuntimeError):
            linux_mod.LinuxBackend(pid=1, engine="pipewire-native")


class TestAutoDetect:
    def test_auto_pipewire_with_native(self, linux_mod, patch_strategies, monkeypatch):
        patch_strategies()
        monkeypatch.setattr(linux_mod, "detect_audio_server", lambda: "pipewire")
        monkeypatch.setattr(linux_mod, "PIPEWIRE_NATIVE_AVAILABLE", True)
        b = linux_mod.LinuxBackend(pid=1, engine="auto")
        assert _label(b) == "native"

    def test_auto_pipewire_without_native(self, linux_mod, patch_strategies, monkeypatch):
        patch_strategies()
        monkeypatch.setattr(linux_mod, "detect_audio_server", lambda: "pipewire")
        monkeypatch.setattr(linux_mod, "PIPEWIRE_NATIVE_AVAILABLE", False)
        b = linux_mod.LinuxBackend(pid=1, engine="auto")
        assert _label(b) == "pipewire"

    def test_auto_pulseaudio(self, linux_mod, patch_strategies, monkeypatch):
        patch_strategies()
        monkeypatch.setattr(linux_mod, "detect_audio_server", lambda: "pulseaudio")
        b = linux_mod.LinuxBackend(pid=1, engine="auto")
        assert _label(b) == "pulse"

    def test_auto_unknown_defaults_to_pulse(self, linux_mod, patch_strategies, monkeypatch):
        patch_strategies()
        monkeypatch.setattr(linux_mod, "detect_audio_server", lambda: "unknown")
        b = linux_mod.LinuxBackend(pid=1, engine="auto")
        assert _label(b) == "pulse"


class TestBackendFormat:
    def test_get_format_is_standard(self, linux_mod, patch_strategies):
        patch_strategies()
        b = linux_mod.LinuxBackend(pid=1, engine="pulse")
        fmt = b.get_format()
        assert fmt["sample_rate"] == 48000
        assert fmt["channels"] == 2
        assert fmt["bits_per_sample"] == 32
        assert fmt["sample_format"] == "float32"
