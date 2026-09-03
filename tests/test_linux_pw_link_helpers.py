"""Tests for the pure pw-link / pw-dump helpers in :mod:`proctap.backends.linux`.

These helpers underpin the Issue #48 fix that replaces the
``sink_input_move`` + name-targeted ``pw-record`` approach (which WirePlumber
reverts / mis-routes) with explicit ``pw-link`` port connections resolved by
global id from a single ``pw-dump`` snapshot.

The helpers are pure (no PipeWire daemon required), so these tests run on
any platform.
"""
from __future__ import annotations

import json

import pytest

from proctap.backends.linux import (
    _pw_coerce_int,
    _pw_dump_parse,
    _pw_find_node_id_by_name,
    _pw_find_ports,
    _pw_find_stream_node_ids_by_pid,
    _pw_link_already_linked,
    _pw_link_nodes,
    _pw_obj_props,
)


def _node(node_id: int, name: str, media_class: str, pid: int | None = None) -> dict:
    props: dict = {"node.name": name, "media.class": media_class}
    if pid is not None:
        props["application.process.id"] = str(pid)
    return {
        "id": node_id,
        "type": "PipeWire:Interface:Node",
        "info": {"props": props},
    }


def _port(port_id: int, node_id: int, direction: str, channel: str) -> dict:
    return {
        "id": port_id,
        "type": "PipeWire:Interface:Port",
        "info": {
            "props": {
                "node.id": str(node_id),
                "port.direction": direction,
                "audio.channel": channel,
            }
        },
    }


@pytest.fixture
def sample_dump() -> list[dict]:
    """A pw-dump snapshot mimicking the WirePlumber repro environment."""
    return [
        _node(100, "proctap_pw_isolated_42", "Audio/Sink"),
        _node(101, "VRChat.exe", "Stream/Output/Audio", pid=42),
        _node(102, "VRChat.exe", "Stream/Output/Audio", pid=99),  # different PID
        _node(103, "proctap_pw_rec_42", "Stream/Input/Audio"),
        _port(200, 101, "out", "FL"),
        _port(201, 101, "out", "FR"),
        _port(202, 102, "out", "FL"),  # other PID
        _port(300, 100, "in", "FL"),
        _port(301, 100, "in", "FR"),
        _port(310, 100, "out", "FL"),  # null-sink monitor
        _port(311, 100, "out", "FR"),
        _port(400, 103, "in", "FL"),  # recorder input
        _port(401, 103, "in", "FR"),
    ]


class TestPwDumpParse:
    def test_empty_input_returns_empty(self):
        assert _pw_dump_parse(b"") == []

    def test_invalid_json_returns_empty(self):
        assert _pw_dump_parse(b"not json {") == []

    def test_non_array_root_returns_empty(self):
        assert _pw_dump_parse(b'{"id": 1}') == []

    def test_drops_non_dict_elements(self):
        raw = json.dumps([{"id": 1}, "string", 7, None, {"id": 2}]).encode()
        result = _pw_dump_parse(raw)
        assert [o["id"] for o in result] == [1, 2]


class TestPwObjProps:
    def test_returns_empty_dict_when_no_info(self):
        assert _pw_obj_props({"id": 1}) == {}

    def test_returns_empty_dict_when_no_props(self):
        assert _pw_obj_props({"info": {}}) == {}

    def test_returns_props_when_present(self):
        obj = {"info": {"props": {"k": "v"}}}
        assert _pw_obj_props(obj) == {"k": "v"}


class TestPwCoerceInt:
    @pytest.mark.parametrize("value,expected", [
        (1, 1),
        ("42", 42),
        ("0", 0),
        (None, None),
        ("not a number", None),
        ("3.14", None),
        ([], None),
    ])
    def test_coerces(self, value, expected):
        assert _pw_coerce_int(value) == expected


class TestFindNodeIdByName:
    def test_found(self, sample_dump):
        assert _pw_find_node_id_by_name(sample_dump, "proctap_pw_isolated_42") == 100

    def test_not_found(self, sample_dump):
        assert _pw_find_node_id_by_name(sample_dump, "no_such_node") is None

    def test_skips_ports(self, sample_dump):
        # Even if a port happened to have node.name in its props it must not match.
        assert _pw_find_node_id_by_name(sample_dump, "FL") is None


class TestFindStreamNodeIdsByPid:
    def test_returns_only_matching_pid(self, sample_dump):
        assert _pw_find_stream_node_ids_by_pid(sample_dump, 42) == [101]

    def test_returns_empty_when_pid_absent(self, sample_dump):
        assert _pw_find_stream_node_ids_by_pid(sample_dump, 7777) == []

    def test_ignores_audio_sink_node(self, sample_dump):
        # Audio/Sink (id=100) must never be returned as a producer.
        result = _pw_find_stream_node_ids_by_pid(sample_dump, 42)
        assert 100 not in result

    def test_returns_multiple_streams_for_same_pid(self):
        dump = [
            _node(10, "App", "Stream/Output/Audio", pid=1),
            _node(11, "App", "Stream/Output/Audio", pid=1),
            _node(12, "Other", "Stream/Output/Audio", pid=2),
        ]
        assert sorted(_pw_find_stream_node_ids_by_pid(dump, 1)) == [10, 11]


class TestFindPorts:
    def test_producer_out_ports(self, sample_dump):
        assert _pw_find_ports(sample_dump, 101, "out") == {"FL": 200, "FR": 201}

    def test_tap_in_ports(self, sample_dump):
        assert _pw_find_ports(sample_dump, 100, "in") == {"FL": 300, "FR": 301}

    def test_tap_monitor_ports(self, sample_dump):
        assert _pw_find_ports(sample_dump, 100, "out") == {"FL": 310, "FR": 311}

    def test_recorder_in_ports(self, sample_dump):
        assert _pw_find_ports(sample_dump, 103, "in") == {"FL": 400, "FR": 401}

    def test_direction_filter_excludes_other_direction(self, sample_dump):
        # node 100 has both in and out ports; out filter must exclude in ports.
        out_ports = _pw_find_ports(sample_dump, 100, "out")
        in_ports = _pw_find_ports(sample_dump, 100, "in")
        assert set(out_ports.values()).isdisjoint(set(in_ports.values()))


class TestPwLinkAlreadyLinked:
    def test_file_exists_signals_already_linked(self):
        assert _pw_link_already_linked("failed to link ports: File exists") is True

    def test_other_error_does_not(self):
        assert _pw_link_already_linked("failed to link ports: No such file or directory") is False

    def test_empty_stderr(self):
        assert _pw_link_already_linked("") is False


class TestPwLinkNodes:
    """Exercise the channel-matching loop with a stubbed pw-link runner."""

    def test_links_every_shared_channel(self, sample_dump, monkeypatch):
        calls: list[tuple[int, int]] = []

        def fake_link(out_id: int, in_id: int) -> bool:
            calls.append((out_id, in_id))
            return True

        monkeypatch.setattr("proctap.backends.linux._pw_link_ports", fake_link)

        # Producer (node 101) FL/FR -> tap (node 100) FL/FR
        linked = _pw_link_nodes(sample_dump, 101, "out", 100, "in")
        assert linked == 2
        assert sorted(calls) == [(200, 300), (201, 301)]

    def test_skips_channels_missing_on_destination(self, monkeypatch):
        dump = [
            _port(1, 10, "out", "FL"),
            _port(2, 10, "out", "FR"),
            _port(3, 20, "in", "FL"),  # FR missing on destination
        ]
        calls: list[tuple[int, int]] = []
        monkeypatch.setattr(
            "proctap.backends.linux._pw_link_ports",
            lambda a, b: calls.append((a, b)) or True,
        )

        linked = _pw_link_nodes(dump, 10, "out", 20, "in")
        assert linked == 1
        assert calls == [(1, 3)]

    def test_counts_failed_links_separately(self, monkeypatch):
        dump = [
            _port(1, 10, "out", "FL"),
            _port(2, 10, "out", "FR"),
            _port(3, 20, "in", "FL"),
            _port(4, 20, "in", "FR"),
        ]

        def flaky(out_id: int, in_id: int) -> bool:
            return out_id == 1  # FL succeeds, FR fails

        monkeypatch.setattr("proctap.backends.linux._pw_link_ports", flaky)

        linked = _pw_link_nodes(dump, 10, "out", 20, "in")
        assert linked == 1
