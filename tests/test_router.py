import pytest

from gyromote import macos
from gyromote.router import Router

WHEEL = {"press": "mouse.left_click", "move": "mouse.left_down", "move_threshold": 8,
         "hold": {"after": 0.4, "down": "mouse.alt+left_down", "apps": ["com.apple.Terminal"]}}


def recording(cfg, **kw):
    ran = []
    r = Router(cfg, pointer=None, dry_run=True, **kw)
    r.run_action = lambda a: ran.append(("run", a))
    r.release_action = lambda a: ran.append(("rel", a))
    return r, ran


def test_press_move_and_hold_gestures(monkeypatch):
    r, ran = recording({"buttons": {"wheel": WHEEL}})

    r.button_down("wheel", 0.0); r.tick(0.1); r.button_up("wheel")
    assert ran == [("run", "mouse.left_click"), ("rel", "mouse.left_click")]

    ran.clear(); r.button_down("wheel", 0.0); r.pointer_moved(3, 2)
    assert r.pending is not None
    r.pointer_moved(5, 0); r.button_up("wheel")
    assert ran == [("run", "mouse.left_down"), ("rel", "mouse.left_down")]

    monkeypatch.setattr(macos, "frontmost_bundle_id", lambda: "com.apple.Terminal")
    ran.clear(); r.button_down("wheel", 0.0); r.tick(0.5); r.button_up("wheel")
    assert ran == [("run", "mouse.alt+left_down"), ("rel", "mouse.alt+left_down")]

    monkeypatch.setattr(macos, "frontmost_bundle_id", lambda: "com.apple.Safari")
    ran.clear(); r.button_down("wheel", 0.0); r.tick(0.5); r.button_up("wheel")
    assert ran == [("run", "mouse.left_down"), ("rel", "mouse.left_down")]


def test_hold_up_runs_after_release():
    r, ran = recording({"buttons": {"prime": {"press": "pointer.toggle", "hold": {"after": 0.4, "down": "app:ptt down", "up": "app:ptt up"}}}})
    r.button_down("prime", 0.0); r.tick(0.5); r.button_up("prime")
    assert ran == [("run", "app:ptt down"), ("rel", "app:ptt down"), ("run", "app:ptt up")]


def test_repeat_then_switches_action():
    r, ran = recording({"buttons": {"netflix": {"down": "key.backspace", "repeat": {
        "delay": 0.35, "interval": 0.07, "switch_after": 2, "then": "key.alt+backspace", "then_interval": 0.15}}}})
    r.button_down("netflix", 0.0)
    for t in (0.1, 0.36, 0.40, 0.44, 0.52, 0.60, 0.68):
        r.tick(t)
    r.button_up("netflix"); r.tick(5.0)
    taps = [a for kind, a in ran if kind == "run"]
    assert taps == ["key.backspace", "key.backspace", "key.backspace", "key.alt+backspace", "key.alt+backspace"]


def test_flags_overlay_in_config_order_and_press_owner_survives_a_flip():
    cfg = {"buttons": {"mic": {"down": "shell:start", "up": "shell:stop"}, "up": "key.up"},
           "wheel": {"action": "scroll"},
           "flags": {"quiet": {"default": True, "buttons": {"mic": "none"}},
                     "slides": {"wheel": {"action": "buttons", "up_action": "key.left"}},
                     "later": {"buttons": {"mic": "key.m"}}}}
    r, ran = recording(cfg)
    assert r.flags == {"quiet": True, "slides": False, "later": False} and r.buttons_cfg["mic"] == "none"
    r.set_flag("later", True)
    assert r.buttons_cfg["mic"] == "key.m"
    r.set_flag("slides", True)
    assert r.wheel_cfg["action"] == "buttons"

    r.set_flag("quiet", False); r.set_flag("later", False)
    r.button_down("mic", 0.0); r.set_flag("quiet", True); r.button_up("mic")
    assert ran == [("run", "shell:start"), ("run", "shell:stop")]


def test_through_intercept_arms_only_marked_holds_and_early_release_sends_nothing():
    cfg = {"buttons": {"back": {"press": "key.escape", "hold": {"after": 1.0, "down": "app:take", "through_intercept": True}},
                       "wheel": WHEEL}}
    r, ran = recording(cfg)
    r.arm_hold_only("back", 0.0); r.tick(1.1); r.button_up("back")
    assert ran == [("run", "app:take"), ("rel", "app:take")]

    ran.clear(); r.arm_hold_only("back", 0.0); r.button_up("back")
    assert [a for _, a in ran if a] == []

    ran.clear(); r.arm_hold_only("wheel", 0.0); r.tick(1.1); r.button_up("wheel")
    assert ran == [] and r.pending is None


def test_host_actions_get_the_full_string_and_unknown_ones_do_nothing(caplog):
    got = []
    r = Router({}, pointer=None, actions={"app:": got.append})
    r.run_action("app:ptt state=down")
    r.run_action("other:thing")
    assert got == ["app:ptt state=down"] and "unknown action other:thing" in caplog.text


def test_wheel_scrolls_inverted_or_fires_actions(posted):
    r = Router({"wheel": {"action": "scroll", "lines": 3, "invert": True}}, pointer=None)
    r.wheel(1); r.wheel(0)
    assert posted == [("post_scroll", -3)]
    r2, ran = recording({"wheel": {"action": "buttons", "up_action": "key.left", "down_action": "key.right"}})
    r2.wheel(1); r2.wheel(-1)
    assert ran == [("run", "key.left"), ("run", "key.right")]


@pytest.mark.parametrize("cfg,name", [
    ({"buttons": {"wheel": "mouse.alt+left_down"}}, "wheel"),
    ({"buttons": {"wheel": {**WHEEL, "hold": {**WHEEL["hold"], "apps": None}}}}, "wheel"),
    ({"buttons": {"up": "key.cmd+shift+up"}}, "up"),
])
def test_release_all_lets_go_of_held_keys_mouse_and_modifiers(posted, cfg, name):
    r = Router(cfg, pointer=None)
    r.button_down(name, 0.0); r.tick(1.0)
    posted.clear()
    r.release_all()
    kinds = [c[0] for c in posted]
    assert kinds[-1] == "post_flags_reset"
    if "mouse" in str(cfg):
        assert ("post_mouse_button", "left", False, macos.MODIFIERS["alt"][0]) in posted
        assert ("post_modifiers", [macos.MODIFIERS["alt"]], False) in posted
        assert r.left_down is False and r.mouse_flags == 0
    else:
        assert posted[0][0] == "post_key" and posted[0][3] is False
    assert r.pressed == {} and r.held is None and r.held_action is None
