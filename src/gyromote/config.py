from pathlib import Path

import yaml

from . import macos


class ConfigError(ValueError):
    pass


def load_config(path) -> dict:
    path = Path(path)
    if path.stat().st_mode & 0o002:
        raise ConfigError(f"{path}: world-writable; shell: actions in it would run as you")
    cfg = yaml.safe_load(path.read_text()) or {}
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return cfg


def validate_config(cfg: dict, actions=()) -> None:
    flags = cfg.get("flags") or {}
    prefixes = tuple(actions)

    def action(value, path):
        if value is None or value == "none":
            return
        if not isinstance(value, str):
            raise ConfigError(f"{path}: action must be a string, got {value!r}")
        try:
            if value.startswith("key."):
                macos.parse_combo(value[len("key."):])
                return
            if value.startswith("mouse."):
                _, _, what = macos.parse_mouse(value[len("mouse."):])
                button, _, verb = what.rpartition("_")
                if button not in macos.MOUSE_BUTTONS or verb not in ("click", "down"):
                    raise ValueError(f"unknown mouse action: {what}")
                return
        except ValueError as e:
            raise ConfigError(f"{path}: {e}") from None
        for prefix in ("flag.on:", "flag.off:", "flag.toggle:"):
            if value.startswith(prefix):
                if value[len(prefix):] not in flags:
                    raise ConfigError(f"{path}: unknown flag {value[len(prefix):]!r}")
                return
        if value.startswith("shell:") and value[len("shell:"):].strip():
            return
        if value in ("pointer.toggle", "pointer.calibrate") or value in macos.MEDIA_KEY_CODES or value in macos.SPACES_KEYCODES:
            return
        if prefixes and value.startswith(prefixes):
            return
        raise ConfigError(f"{path}: unknown action {value!r}")

    def button(spec, path):
        if not isinstance(spec, dict):
            action(spec, path)
            return
        for key in ("down", "up", "press", "move"):
            action(spec.get(key), f"{path}.{key}")
        hold = spec.get("hold")
        if hold is not None:
            if not isinstance(hold, dict):
                raise ConfigError(f"{path}.hold: must be a mapping")
            action(hold.get("down"), f"{path}.hold.down")
            action(hold.get("up"), f"{path}.hold.up")
        repeat = spec.get("repeat")
        if repeat is not None:
            if not isinstance(repeat, dict) or "then" not in repeat:
                raise ConfigError(f"{path}.repeat: must be a mapping with `then`")
            action(repeat["then"], f"{path}.repeat.then")

    def layer(section, path):
        for name, spec in (section.get("buttons") or {}).items():
            button(spec, f"{path}buttons.{name}")
        wheel = section.get("wheel") or {}
        if wheel.get("action", "scroll") not in ("scroll", "buttons"):
            raise ConfigError(f"{path}wheel.action: must be scroll or buttons")
        for key in ("up_action", "down_action"):
            action(wheel.get(key), f"{path}wheel.{key}")

    layer(cfg, "")
    for name, flag in flags.items():
        layer(flag or {}, f"flags.{name}.")
