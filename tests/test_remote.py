import json

import pytest
from fakes import Dev, frame, wait_for

from gyromote import macos
from gyromote import remote as remote_mod
from gyromote.pointer import Pointer
from gyromote.remote import Remote

MIC, UP, WHEEL = 0x808B, 0x8040, 0x8044


@pytest.fixture
def devices(monkeypatch):
    queue = []
    monkeypatch.setattr(remote_mod, "open_device", lambda vid, pid: queue.pop(0) if queue else None)
    monkeypatch.setattr(remote_mod, "RETRY_S", 0.02)
    monkeypatch.setattr(remote_mod, "READ_ERROR_PAUSE_S", 0.02)
    return queue


def start(cfg, tmp_path, **kw):
    events = []
    r = Remote({"pointer": {"enabled": False}, **cfg}, on_event=events.append, on_toast=lambda t: None,
               calibration_path=tmp_path / "calibration.json", **kw)
    r.start()
    return r, events


def test_held_button_is_released_when_the_remote_drops_and_stays_away(devices, posted, tmp_path, monkeypatch):
    monkeypatch.setattr(remote_mod, "LOST_UP_S", 0.1)
    devices.append(Dev([frame(1, MIC), frame(2, MIC)]))
    r, events = start({"buttons": {"mic": "key.m"}}, tmp_path)
    try:
        mic = lambda: [e for e in events if e.get("name") == "mic"]  # noqa: E731
        assert wait_for(lambda: len(mic()) == 2)
        assert mic() == [{"type": "button", "name": "mic", "code": "0x808B", "state": "down", "mouse": False},
                         {"type": "button", "name": "mic", "code": "0x808B", "state": "up", "lost": True}]
        assert [e for e in events if e["type"] == "device"] == [{"type": "device", "state": "connected"},
                                                                 {"type": "device", "state": "disconnected"}]
        assert ("post_key", 0x2E, [], False) in posted
    finally:
        r.stop()


def test_event_schema_for_buttons_repeat_and_wheel(devices, posted, tmp_path):
    reports = [frame(1), frame(2, UP)] + [frame(3, UP)] * 2 + [frame(3 + i, UP) for i in range(1, 12)]
    reports += [frame(20), frame(21, wheel=1), frame(22, wheel=-1), frame(22, wheel=-1), frame(23)]
    devices.append(Dev(reports, then="repeat"))
    r, events = start({"poll_hz": 200, "repeat_delay": 0.02, "repeat_interval": 0.01,
                       "buttons": {"up": "key.up"}, "wheel": {"lines": 3}}, tmp_path)
    try:
        assert wait_for(lambda: sum(e["type"] == "wheel" for e in events) == 2)
    finally:
        r.stop()
    up = [e for e in events if e.get("name") == "up"]
    assert up[0] == {"type": "button", "name": "up", "code": "0x8040", "state": "down", "mouse": False}
    assert {e["state"] for e in up[1:-1]} == {"repeat"} and len(up) > 2
    assert up[-1] == {"type": "button", "name": "up", "code": "0x8040", "state": "up"}
    assert [e for e in events if e["type"] == "wheel"] == [{"type": "wheel", "delta": 1, "mouse": False},
                                                            {"type": "wheel", "delta": -1, "mouse": False}]
    assert [c for c in posted if c[0] == "post_scroll"] == [("post_scroll", 3), ("post_scroll", -3)]


def test_intercepted_button_only_emits_and_wheel_click_wakes_the_cursor(devices, posted, tmp_path):
    devices.append(Dev([frame(1), frame(2, UP), frame(3), frame(4, WHEEL), frame(5)], then="repeat"))
    r, events = start({"buttons": {"up": "key.up", "wheel": "mouse.left_click"}}, tmp_path,
                      intercept=lambda name: name == "up")
    try:
        assert wait_for(lambda: r.pointer_enabled)
    finally:
        r.stop()
    assert not [c for c in posted if c[0] in ("post_key", "post_click")]
    assert [e["name"] for e in events if e.get("state") == "down"] == ["up", "wheel"]


def test_stop_releases_what_is_held(devices, posted, tmp_path):
    devices.append(Dev([frame(1, UP)], then="repeat"))
    r, events = start({"buttons": {"up": "mouse.alt+left_down"}}, tmp_path)
    assert wait_for(lambda: any(c[0] == "post_mouse_button" and c[2] is True for c in posted))
    r.stop()
    released = posted[[c[0] for c in posted].index("post_mouse_button") + 1:]
    assert ("post_mouse_button", "left", False, released[0][3]) == released[0]
    assert [c[0] for c in released][-1] == "post_flags_reset"
    assert ("post_modifiers", [macos.MODIFIERS["alt"]], False) in released
    assert not [e for e in events if e.get("state") == "up"], "stop releases input, it does not fake a button up"


def test_flags_persist_and_emit(tmp_path):
    path = tmp_path / "flags.json"
    events, toasts = [], []
    flags = {"live": {"default": False, "title": "Live"}, "tv": {"default": False}}
    first = Remote({"flags": flags}, on_event=events.append, on_toast=toasts.append, flags_path=path,
                   calibration_path=tmp_path / "c.json")
    first.set_flag("live", True)
    assert events == [{"type": "flag", "name": "live", "on": True, "flags": {"live": True, "tv": False}}]
    assert toasts == ["Live: on"] and json.loads(path.read_text()) == {"live": True, "tv": False}

    second = Remote({"flags": {"live": {"default": False}, "slides": {"default": True}}}, flags_path=path,
                    calibration_path=tmp_path / "c.json")
    assert second.flags == {"live": True, "slides": True}


def test_calibration_writes_bias_to_its_path_and_next_start_loads_it(tmp_path):
    path = tmp_path / "sub/calibration.json"
    events = []
    pt = Pointer({"calibration_samples": 3, "dead_zone": 0, "smoothing": 0.0, "sensitivity": 1.0}, path, emit=events.append)
    assert pt.bias == [0.0, 0.0, 0.0]
    pt.calibrate()
    for _ in range(3):
        assert pt.update([10, 20, 30], False) is None
    assert json.loads(path.read_text()) == {"gyro_bias": [10.0, 20.0, 30.0]}
    assert events == [{"type": "calibration", "state": "start"},
                      {"type": "calibration", "state": "done", "bias": [10.0, 20.0, 30.0]}]
    assert pt.update([10, 20, 30], False) == (0.0, 0.0)
    assert Pointer({}, path).bias == [10.0, 20.0, 30.0]
