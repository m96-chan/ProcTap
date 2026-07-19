"""
Characterization tests for the Linux PulseAudio / PipeWire capture strategies.

These lock in the observable behaviour of ``PulseAudioStrategy`` and
``PipeWireStrategy`` so the de-duplication refactor in Issue #26 (extracting a
shared PulseAudio-compat base class) can be verified to preserve behaviour.

The real backends need ``pulsectl`` (Linux only) plus the ``parec`` / ``pw-record``
binaries, none of which exist in CI on macOS/Windows. We therefore inject a fake
``pulsectl`` module and fake ``subprocess`` primitives so the pure orchestration
logic can be exercised on any platform.
"""

import io
import queue
import sys
import types
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Fake pulsectl infrastructure
# ---------------------------------------------------------------------------

class FakeSinkInput:
    def __init__(self, index, pid=None, name="App", stream_id=None, sink=0):
        self.index = index
        self.sink = sink
        proplist = {"application.name": name}
        if pid is not None:
            proplist["application.process.id"] = str(pid)
        if stream_id is not None:
            proplist["pipewire.stream.id"] = stream_id
        self.proplist = proplist


class FakeSink:
    def __init__(self, index, name, monitor_source_name="monitor.src"):
        self.index = index
        self.name = name
        self.monitor_source_name = monitor_source_name


class RaisingMonitorSink:
    """A sink whose monitor_source_name access fails (step-3 error path)."""

    def __init__(self, index, name):
        self.index = index
        self.name = name

    @property
    def monitor_source_name(self):
        raise RuntimeError("monitor source unavailable")


class FakePulse:
    """Minimal stand-in for pulsectl.Pulse recording the calls made against it."""

    def __init__(self, client_name=None):
        self.client_name = client_name
        self.closed = False
        self.sink_inputs = []
        self.sinks = []
        self.loaded_modules = {}
        self.moved = []
        self._next_module = 100
        # Error-injection switches
        self.fail_module_load = False
        self.fail_move = False
        self.fail_unload = False
        self.missing_monitor_sink = False
        self.monitor_raises = False

    def sink_input_list(self):
        return list(self.sink_inputs)

    def sink_input_info(self, index):
        for si in self.sink_inputs:
            if si.index == index:
                return si
        raise RuntimeError(f"no sink input {index}")

    def sink_list(self):
        return list(self.sinks)

    def sink_info(self, index):
        for s in self.sinks:
            if s.index == index:
                return s
        raise RuntimeError(f"no sink {index}")

    def module_load(self, name, args=""):
        if self.fail_module_load:
            raise RuntimeError("module_load failed")
        idx = self._next_module
        self._next_module += 1
        self.loaded_modules[idx] = name
        # Emulate the null-sink appearing with the requested sink_name.
        sink_name = None
        for token in args.split():
            if token.startswith("sink_name="):
                sink_name = token.split("=", 1)[1]
                break
        if sink_name and not self.missing_monitor_sink:
            if self.monitor_raises:
                self.sinks.append(RaisingMonitorSink(index=900 + idx, name=sink_name))
            else:
                self.sinks.append(FakeSink(index=900 + idx, name=sink_name))
        return idx

    def module_unload(self, index):
        if self.fail_unload:
            raise RuntimeError("module_unload failed")
        self.loaded_modules.pop(index, None)

    def sink_input_move(self, index, sink_index):
        if self.fail_move:
            raise RuntimeError("sink_input_move failed")
        self.moved.append((index, sink_index))

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fake_pulsectl(monkeypatch):
    """Install a fake ``pulsectl`` module and make ``which pw-record`` succeed."""
    fake_module = types.ModuleType("pulsectl")
    fake_module.Pulse = FakePulse  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pulsectl", fake_module)

    import proctap.backends.linux as linux_mod

    # pw-record availability probe used by PipeWireStrategy.__init__
    monkeypatch.setattr(
        linux_mod.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(returncode=0),
    )
    return fake_module


@pytest.fixture
def linux_mod():
    import proctap.backends.linux as linux_mod
    return linux_mod


class NoRunThread:
    """threading.Thread replacement that records config but never runs target."""

    instances = []

    def __init__(self, target=None, args=(), daemon=None, **kwargs):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False
        NoRunThread.instances.append(self)

    def start(self):
        self.started = True

    def is_alive(self):
        return False

    def join(self, timeout=None):
        pass


@pytest.fixture
def no_threads(monkeypatch, linux_mod):
    NoRunThread.instances = []
    monkeypatch.setattr(linux_mod.threading, "Thread", NoRunThread)
    return NoRunThread


def _connected(strategy):
    strategy.connect()
    return strategy._pulse


# ---------------------------------------------------------------------------
# __init__ behaviour
# ---------------------------------------------------------------------------

class TestInit:
    def test_pulse_defaults(self, linux_mod):
        s = linux_mod.PulseAudioStrategy(pid=42)
        assert s._pid == 42
        assert s._sample_rate == 44100
        assert s._channels == 2
        assert s._sample_width == 2
        assert s._bits_per_sample == 16
        assert s._audio_queue.maxsize == 50

    def test_pipewire_defaults(self, linux_mod, no_threads):
        s = linux_mod.PipeWireStrategy(pid=7)
        assert s._pid == 7
        assert s._sample_rate == 48000  # PipeWire default differs from PulseAudio
        assert s._bits_per_sample == 16

    def test_pulse_requires_pulsectl(self, monkeypatch, linux_mod):
        monkeypatch.setitem(sys.modules, "pulsectl", None)  # import -> ImportError
        with pytest.raises(RuntimeError, match="pulsectl"):
            linux_mod.PulseAudioStrategy(pid=1)

    def test_pipewire_requires_pwrecord(self, monkeypatch, linux_mod):
        monkeypatch.setattr(
            linux_mod.subprocess, "run",
            lambda *a, **k: types.SimpleNamespace(returncode=1),
        )
        with pytest.raises(RuntimeError, match="pw-record"):
            linux_mod.PipeWireStrategy(pid=1)

    def test_pipewire_requires_pulsectl(self, monkeypatch, linux_mod):
        monkeypatch.setitem(sys.modules, "pulsectl", None)
        with pytest.raises(RuntimeError, match="pulsectl"):
            linux_mod.PipeWireStrategy(pid=1)


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------

class TestConnect:
    @pytest.mark.parametrize("cls_name", ["PulseAudioStrategy", "PipeWireStrategy"])
    def test_connect_success(self, linux_mod, cls_name):
        s = getattr(linux_mod, cls_name)(pid=1)
        s.connect()
        assert isinstance(s._pulse, FakePulse)

    @pytest.mark.parametrize("cls_name", ["PulseAudioStrategy", "PipeWireStrategy"])
    def test_connect_failure_wrapped(self, monkeypatch, linux_mod, cls_name):
        s = getattr(linux_mod, cls_name)(pid=1)

        def boom(*a, **k):
            raise OSError("server down")

        s._pulsectl = types.SimpleNamespace(Pulse=boom)
        with pytest.raises(RuntimeError, match="Failed to connect"):
            s.connect()


# ---------------------------------------------------------------------------
# find_process_stream
# ---------------------------------------------------------------------------

class TestFindProcessStream:
    def test_not_connected_raises(self, linux_mod):
        s = linux_mod.PulseAudioStrategy(pid=1)
        with pytest.raises(RuntimeError, match="Not connected"):
            s.find_process_stream(1)

    def test_found(self, linux_mod):
        s = linux_mod.PulseAudioStrategy(pid=1234)
        pulse = _connected(s)
        pulse.sink_inputs = [FakeSinkInput(5, pid=1234, name="Music")]
        assert s.find_process_stream(1234) is True
        assert s._sink_input_index == 5

    def test_not_found(self, linux_mod):
        s = linux_mod.PulseAudioStrategy(pid=1234)
        pulse = _connected(s)
        pulse.sink_inputs = [FakeSinkInput(5, pid=9999)]
        assert s.find_process_stream(1234) is False
        assert s._sink_input_index is None

    def test_exception_returns_false(self, linux_mod):
        s = linux_mod.PulseAudioStrategy(pid=1)
        pulse = _connected(s)
        pulse.sink_input_list = mock.Mock(side_effect=RuntimeError("boom"))
        assert s.find_process_stream(1) is False

    def test_pipewire_captures_stream_id(self, linux_mod):
        s = linux_mod.PipeWireStrategy(pid=1234)
        pulse = _connected(s)
        pulse.sink_inputs = [FakeSinkInput(5, pid=1234, stream_id="pw-77")]
        assert s.find_process_stream(1234) is True
        assert s._sink_input_index == 5
        assert s._stream_id == "pw-77"


# ---------------------------------------------------------------------------
# start_capture + isolation setup
# ---------------------------------------------------------------------------

BOTH = ["PulseAudioStrategy", "PipeWireStrategy"]


class TestStartCapture:
    def _prepare(self, s):
        pulse = _connected(s)
        pulse.sink_inputs = [FakeSinkInput(5, pid=s._pid, sink=3)]
        pulse.sinks = [FakeSink(index=3, name="orig")]
        s.find_process_stream(s._pid)
        return pulse

    def test_requires_stream(self, linux_mod):
        s = linux_mod.PulseAudioStrategy(pid=1)
        _connected(s)
        with pytest.raises(RuntimeError, match="No sink-input"):
            s.start_capture()

    @pytest.mark.parametrize("cls_name", BOTH)
    def test_isolated_success_starts_thread(self, linux_mod, no_threads, cls_name):
        s = getattr(linux_mod, cls_name)(pid=1)
        pulse = self._prepare(s)
        s.start_capture()
        assert len(no_threads.instances) == 1
        assert no_threads.instances[0].started
        # sink-input was moved to the created null-sink
        assert pulse.moved
        assert s._null_sink_index is not None

    def test_pulse_falls_back_to_monitor(self, linux_mod, no_threads):
        s = linux_mod.PulseAudioStrategy(pid=1)
        pulse = self._prepare(s)
        pulse.fail_module_load = True  # isolation setup fails
        s.start_capture()
        assert s._isolation_mode == "monitor"
        assert no_threads.instances[-1].started  # monitor capture thread started

    def test_pipewire_has_no_monitor_fallback(self, linux_mod, no_threads):
        s = linux_mod.PipeWireStrategy(pid=1)
        pulse = self._prepare(s)
        pulse.fail_module_load = True
        with pytest.raises(RuntimeError, match="Failed to start PipeWire capture"):
            s.start_capture()


class TestSetupIsolatedCaptureErrors:
    def _prepare(self, linux_mod, cls_name):
        s = getattr(linux_mod, cls_name)(pid=1)
        pulse = _connected(s)
        pulse.sink_inputs = [FakeSinkInput(5, pid=1, sink=3)]
        pulse.sinks = [FakeSink(index=3, name="orig")]
        s.find_process_stream(1)
        s._original_sink_index = 3
        s._sink_input_index = 5
        return s, pulse

    @pytest.mark.parametrize("cls_name", BOTH)
    def test_null_sink_load_failure(self, linux_mod, no_threads, cls_name):
        s, pulse = self._prepare(linux_mod, cls_name)
        pulse.fail_module_load = True
        with pytest.raises(RuntimeError, match="Failed to load null-sink"):
            s._setup_isolated_capture()

    @pytest.mark.parametrize("cls_name", BOTH)
    def test_move_failure_unloads_null_sink(self, linux_mod, no_threads, cls_name):
        s, pulse = self._prepare(linux_mod, cls_name)
        pulse.fail_move = True
        with pytest.raises(RuntimeError, match="move"):
            s._setup_isolated_capture()
        # null-sink module was unloaded during cleanup
        assert pulse.loaded_modules == {}

    @pytest.mark.parametrize("cls_name", BOTH)
    def test_move_failure_unload_also_fails(self, linux_mod, no_threads, cls_name):
        # Exercises the swallow-on-cleanup path when unloading the null-sink
        # after a failed move itself raises (Issue #36 bare-except location).
        s, pulse = self._prepare(linux_mod, cls_name)
        pulse.fail_move = True
        pulse.fail_unload = True
        with pytest.raises(RuntimeError, match="move"):
            s._setup_isolated_capture()

    @pytest.mark.parametrize("cls_name", BOTH)
    def test_missing_monitor_source(self, linux_mod, no_threads, cls_name):
        s, pulse = self._prepare(linux_mod, cls_name)
        pulse.missing_monitor_sink = True  # null-sink never appears in sink_list
        with pytest.raises(RuntimeError):
            s._setup_isolated_capture()

    @pytest.mark.parametrize("cls_name", BOTH)
    def test_monitor_source_lookup_failure_cleans_up(self, linux_mod, no_threads, cls_name):
        # Sink exists (move succeeds) but reading its monitor source fails at step 3.
        s, pulse = self._prepare(linux_mod, cls_name)
        pulse.monitor_raises = True
        with pytest.raises(RuntimeError, match="monitor source"):
            s._setup_isolated_capture()
        # Step-3 failure must unwind the isolation modules it created.
        assert s._null_sink_index is None


# ---------------------------------------------------------------------------
# capture command building + worker loop
# ---------------------------------------------------------------------------

class FakeProc:
    def __init__(self, chunks, wait_timeout=False):
        self.stdout = io.BytesIO(b"".join(chunks))
        self.terminated = False
        self.killed = False
        self._wait_timeout = wait_timeout

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        if self._wait_timeout:
            import subprocess as _sp
            raise _sp.TimeoutExpired("cmd", timeout)
        return 0

    def kill(self):
        self.killed = True


class TestCaptureWorker:
    def _chunk_bytes(self, s):
        frames = int(s._sample_rate * (s._chunk_duration_ms / 1000.0))
        return frames * s._channels * s._sample_width

    def test_pulse_uses_parec(self, linux_mod, monkeypatch):
        s = linux_mod.PulseAudioStrategy(pid=1)
        cb = self._chunk_bytes(s)
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return FakeProc([b"\x01" * cb, b"\x02" * cb])

        monkeypatch.setattr(linux_mod.subprocess, "Popen", fake_popen)
        s._capture_worker("mysource")
        assert captured["cmd"][0] == "parec"
        assert "mysource" in captured["cmd"]
        assert s._audio_queue.qsize() == 2

    def test_pipewire_uses_pwrecord(self, linux_mod, monkeypatch):
        s = linux_mod.PipeWireStrategy(pid=1)
        cb = self._chunk_bytes(s)
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return FakeProc([b"\x01" * cb])

        monkeypatch.setattr(linux_mod.subprocess, "Popen", fake_popen)
        # Both strategies expose the same worker entrypoint after refactor; before
        # refactor PipeWire uses _capture_worker_pwrecord. Call whichever exists.
        worker = getattr(s, "_capture_worker_pwrecord", None) or s._capture_worker
        worker("mysource")
        assert captured["cmd"][0] == "pw-record"
        assert s._audio_queue.qsize() == 1

    def test_queue_full_drops_oldest(self, linux_mod, monkeypatch):
        s = linux_mod.PulseAudioStrategy(pid=1)
        cb = self._chunk_bytes(s)
        # Shrink the queue and pre-fill it so the worker must drop frames.
        s._audio_queue = queue.Queue(maxsize=1)
        s._audio_queue.put(b"old")

        def fake_popen(cmd, **kwargs):
            return FakeProc([b"\x03" * cb, b"\x04" * cb])

        monkeypatch.setattr(linux_mod.subprocess, "Popen", fake_popen)
        s._capture_worker("src")
        # Queue never exceeds its maxsize and ends with the newest chunk.
        assert s._audio_queue.qsize() == 1
        assert s._audio_queue.get() == b"\x04" * cb

    def test_worker_popen_failure_is_logged_not_raised(self, linux_mod, monkeypatch):
        s = linux_mod.PulseAudioStrategy(pid=1)

        def boom(*a, **k):
            raise FileNotFoundError("parec missing")

        monkeypatch.setattr(linux_mod.subprocess, "Popen", boom)
        # Worker must swallow the error (runs on a background thread).
        s._capture_worker("src")
        assert s._audio_queue.qsize() == 0

    def test_worker_no_stdout_breaks(self, linux_mod, monkeypatch):
        s = linux_mod.PulseAudioStrategy(pid=1)
        proc = FakeProc([])
        proc.stdout = None
        monkeypatch.setattr(linux_mod.subprocess, "Popen", lambda *a, **k: proc)
        s._capture_worker("src")
        assert s._audio_queue.qsize() == 0

    def test_worker_read_exception_breaks(self, linux_mod, monkeypatch):
        s = linux_mod.PulseAudioStrategy(pid=1)
        proc = FakeProc([])
        proc.stdout = mock.Mock()
        proc.stdout.read = mock.Mock(side_effect=OSError("read failed"))
        monkeypatch.setattr(linux_mod.subprocess, "Popen", lambda *a, **k: proc)
        s._capture_worker("src")  # error is caught, loop breaks, no raise

    def test_worker_wait_timeout_kills_proc(self, linux_mod, monkeypatch):
        s = linux_mod.PulseAudioStrategy(pid=1)
        cb = self._chunk_bytes(s)
        proc = FakeProc([b"\x01" * cb], wait_timeout=True)
        monkeypatch.setattr(linux_mod.subprocess, "Popen", lambda *a, **k: proc)
        s._capture_worker("src")
        assert proc.killed

    def test_base_build_command_is_abstract(self, linux_mod):
        base = linux_mod._PulseCompatStrategy
        # The base class does not know how to build a recorder command.
        inst = base.__new__(base)
        with pytest.raises(NotImplementedError):
            inst._build_capture_command("src")


# ---------------------------------------------------------------------------
# cleanup / stop / read / close / format
# ---------------------------------------------------------------------------

class TestCleanupAndLifecycle:
    @pytest.mark.parametrize("cls_name", BOTH)
    def test_cleanup_restores_and_unloads(self, linux_mod, cls_name):
        s = getattr(linux_mod, cls_name)(pid=1)
        pulse = _connected(s)
        pulse.sink_inputs = [FakeSinkInput(5, pid=1, sink=3)]
        s._sink_input_index = 5
        s._original_sink_index = 3
        s._null_sink_index = 101
        pulse.loaded_modules[101] = "module-null-sink"
        s._cleanup_isolation_modules()
        assert (5, 3) in pulse.moved            # restored to original sink
        assert 101 not in pulse.loaded_modules  # null-sink unloaded
        assert s._null_sink_index is None

    def test_cleanup_unloads_remap_and_loopback(self, linux_mod):
        # PulseAudioStrategy additionally tracks remap-source / loopback modules.
        s = linux_mod.PulseAudioStrategy(pid=1)
        pulse = _connected(s)
        s._remap_source_index = 201
        s._loopback_module_index = 202
        pulse.loaded_modules.update({201: "module-remap-source", 202: "module-loopback"})
        s._cleanup_isolation_modules()
        assert pulse.loaded_modules == {}
        assert s._remap_source_index is None
        assert s._loopback_module_index is None

    def test_cleanup_remap_loopback_unload_failure_swallowed(self, linux_mod):
        s = linux_mod.PulseAudioStrategy(pid=1)
        pulse = _connected(s)
        s._remap_source_index = 201
        s._loopback_module_index = 202
        pulse.loaded_modules.update({201: "module-remap-source", 202: "module-loopback"})
        pulse.fail_unload = True
        s._cleanup_isolation_modules()  # warnings logged, no raise
        # Indices are still cleared in the finally blocks.
        assert s._remap_source_index is None
        assert s._loopback_module_index is None

    def test_stop_capture_joins_live_thread(self, linux_mod):
        s = linux_mod.PulseAudioStrategy(pid=1)
        _connected(s)
        joined = {"n": 0}

        class LiveThread:
            def is_alive(self_inner):
                return True

            def join(self_inner, timeout=None):
                joined["n"] += 1

        s._capture_thread = LiveThread()
        s.stop_capture()
        assert joined["n"] == 1

    def test_monitor_capture_requires_original_sink(self, linux_mod):
        s = linux_mod.PulseAudioStrategy(pid=1)
        _connected(s)
        s._original_sink_index = None
        with pytest.raises(RuntimeError, match="Original sink index"):
            s._setup_monitor_capture()

    def test_cleanup_restore_failure_is_swallowed(self, linux_mod):
        s = linux_mod.PulseAudioStrategy(pid=1)
        pulse = _connected(s)
        s._sink_input_index = 5
        s._original_sink_index = 3
        pulse.sink_input_info = mock.Mock(side_effect=RuntimeError("gone"))
        s._cleanup_isolation_modules()  # must not raise

    def test_cleanup_no_pulse_is_noop(self, linux_mod):
        s = linux_mod.PulseAudioStrategy(pid=1)
        s._pulse = None
        s._cleanup_isolation_modules()  # returns early, no error

    @pytest.mark.parametrize("cls_name", BOTH)
    def test_cleanup_unload_failure_is_swallowed(self, linux_mod, cls_name):
        s = getattr(linux_mod, cls_name)(pid=1)
        pulse = _connected(s)
        s._null_sink_index = 101
        pulse.loaded_modules[101] = "module-null-sink"
        pulse.fail_unload = True
        s._cleanup_isolation_modules()  # must not raise
        assert s._null_sink_index is None

    @pytest.mark.parametrize("cls_name", BOTH)
    def test_read_audio_returns_data(self, linux_mod, cls_name):
        s = getattr(linux_mod, cls_name)(pid=1)
        s._audio_queue.put(b"pcm")
        assert s.read_audio(timeout=0.1) == b"pcm"

    @pytest.mark.parametrize("cls_name", BOTH)
    def test_read_audio_empty_returns_none(self, linux_mod, cls_name):
        s = getattr(linux_mod, cls_name)(pid=1)
        assert s.read_audio(timeout=0.01) is None

    @pytest.mark.parametrize("cls_name", BOTH)
    def test_stop_capture_sets_stop_event(self, linux_mod, cls_name):
        s = getattr(linux_mod, cls_name)(pid=1)
        _connected(s)
        s.stop_capture()
        assert s._stop_event.is_set()

    @pytest.mark.parametrize("cls_name", BOTH)
    def test_close_closes_pulse(self, linux_mod, cls_name):
        s = getattr(linux_mod, cls_name)(pid=1)
        pulse = _connected(s)
        s.close()
        assert pulse.closed
        assert s._pulse is None

    @pytest.mark.parametrize(
        "cls_name,rate", [("PulseAudioStrategy", 44100), ("PipeWireStrategy", 48000)]
    )
    def test_get_format(self, linux_mod, cls_name, rate):
        s = getattr(linux_mod, cls_name)(pid=1)
        fmt = s.get_format()
        assert fmt == {"sample_rate": rate, "channels": 2, "bits_per_sample": 16}
