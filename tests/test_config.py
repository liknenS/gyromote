import os
from pathlib import Path

import pytest

from gyromote import ConfigError, Remote, load_config, validate_config

EXAMPLE = Path(__file__).parents[1] / "examples/config.yaml"


def test_example_config_loads_and_validates():
    cfg = load_config(EXAMPLE)
    validate_config(cfg)
    assert {"alt_select", "slides"} <= set(cfg["flags"])


@pytest.mark.parametrize("cfg,where", [
    ({"buttons": {"up": "key.uparrow"}}, "buttons.up: unknown key"),
    ({"buttons": {"up": "key.hyper+up"}}, "buttons.up: unknown modifier"),
    ({"buttons": {"up": "mouse.left_up"}}, "buttons.up: unknown mouse action"),
    ({"buttons": {"up": "mouse.alt+side_click"}}, "buttons.up: unknown mouse action"),
    ({"buttons": {"help": {"press": "key.f1", "hold": {"down": "flag.toggle:nope"}}}}, "buttons.help.hold.down: unknown flag"),
    ({"buttons": {"x": {"down": "key.a", "repeat": {"then": "teleport"}}}}, "buttons.x.repeat.then: unknown action"),
    ({"flags": {"f": {"wheel": {"action": "buttons", "up_action": "app:next"}}}}, "flags.f.wheel.up_action: unknown action"),
    ({"wheel": {"action": "spin"}}, "wheel.action"),
    ({"buttons": {"up": "shell:"}}, "buttons.up: unknown action"),
    ({"buttons": {"up": 5}}, "buttons.up: action must be a string"),
])
def test_bad_config_names_the_key(cfg, where):
    with pytest.raises(ConfigError, match=where.replace("(", r"\(")):
        validate_config(cfg)


def test_host_prefixes_are_valid_only_when_registered():
    cfg = {"buttons": {"back": {"press": "key.escape", "hold": {"after": 1.0, "down": "app:take", "through_intercept": True}}}}
    with pytest.raises(ConfigError):
        Remote(cfg)
    Remote(cfg, actions={"app:": lambda a: None}, calibration_path="/nonexistent/c.json")


def test_world_writable_config_is_refused(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("buttons: {up: key.up}\n")
    assert load_config(path) == {"buttons": {"up": "key.up"}}
    os.chmod(path, 0o666)
    with pytest.raises(ConfigError, match="world-writable"):
        load_config(path)
