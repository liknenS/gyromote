import logging
import subprocess

from . import macos

log = logging.getLogger("gyromote")


class Router:
    def __init__(self, cfg, pointer, *, actions=None, dry_run=False):
        self.base_buttons = cfg.get("buttons", {}) or {}
        self.base_wheel = cfg.get("wheel", {}) or {}
        self.flag_cfg = cfg.get("flags", {}) or {}
        self.flags = {name: bool(f.get("default", False)) for name, f in self.flag_cfg.items()}
        self.on_flag = None
        self.actions = dict(actions or {})
        self.apply_flags()
        self.pressed = {}
        self.pointer = pointer
        self.dry_run = dry_run
        self.left_down = False
        self.mouse_flags = 0
        self.held = None
        self.held_action = None
        self.pending = None

    def apply_flags(self):
        buttons, wheel = dict(self.base_buttons), dict(self.base_wheel)
        for name, f in self.flag_cfg.items():
            if self.flags.get(name):
                buttons.update(f.get("buttons") or {})
                wheel.update(f.get("wheel") or {})
        self.buttons_cfg, self.wheel_cfg = buttons, wheel

    def set_flag(self, name, on):
        if name not in self.flag_cfg:
            log.warning(f"unknown flag {name}")
            return
        self.flags[name] = bool(on)
        self.apply_flags()
        log.info(f"flag {name} {'on' if on else 'off'}")
        if self.on_flag:
            self.on_flag(name, bool(on))

    def tap(self, action):
        self.run_action(action)
        self.release_action(action)

    def arm_hold_only(self, name, now):
        entry = self.buttons_cfg.get(name)
        hold = entry.get("hold") if isinstance(entry, dict) else None
        if not hold or not hold.get("through_intercept"):
            return
        if self.pending is not None and self.pending[0] != name:
            return
        self.pressed[name] = {"hold": hold}
        self.pending = (name, self.pressed[name], now + hold.get("after", 0.25), 0.0)

    def start_hold(self, action):
        name, entry, _, _ = self.pending
        self.pending = None
        self.held = (name, entry, None, 0)
        self.held_action = action
        self.run_action(action)

    def pointer_moved(self, dx, dy):
        if self.pending is None or "move" not in self.pending[1]:
            return
        name, entry, due, moved = self.pending
        moved += abs(dx) + abs(dy)
        self.pending = (name, entry, due, moved)
        if moved >= entry.get("move_threshold", 8):
            log.info(f"drag: moved {moved:.0f}px")
            self.start_hold(entry["move"])

    def tick(self, now):
        if self.pending is not None and now >= self.pending[2]:
            hold = self.pending[1]["hold"]
            apps = hold.get("apps")
            allowed = not apps or macos.frontmost_bundle_id() in apps
            self.start_hold(hold.get("down") if allowed else self.pending[1].get("move"))
        if self.held is None or self.held[2] is None:
            return
        name, entry, due, count = self.held
        if now < due:
            return
        rep = entry["repeat"]
        switching = count >= rep.get("switch_after", 6)
        self.tap(rep["then"] if switching else entry.get("down"))
        interval = rep.get("then_interval", 0.15) if switching else rep.get("interval", 0.07)
        self.held = (name, entry, now + interval, count + 1)

    def run_action(self, action):
        if not action or action == "none":
            return
        log.info(f"action {action}")
        if self.dry_run:
            return
        if action.startswith("key."):
            keycode, mods = macos.parse_combo(action[len("key."):])
            macos.post_key(keycode, mods, True)
        elif action.startswith("mouse."):
            flags, mods, what = macos.parse_mouse(action[len("mouse."):])
            button, _, verb = what.rpartition("_")
            macos.post_modifiers(mods, True)
            if verb == "click":
                macos.post_click(button, flags)
                macos.post_modifiers(mods, False)
                if flags:
                    macos.post_flags_reset()
            elif verb == "down":
                macos.post_mouse_button(button, True, flags)
                self.left_down = button == "left"
                self.mouse_flags = flags
            else:
                raise ValueError(f"bad mouse action {action}")
        elif action.startswith("flag.on:"):
            self.set_flag(action[len("flag.on:"):], True)
        elif action.startswith("flag.off:"):
            self.set_flag(action[len("flag.off:"):], False)
        elif action.startswith("flag.toggle:"):
            name = action[len("flag.toggle:"):]
            self.set_flag(name, not self.flags.get(name))
        elif action == "pointer.calibrate":
            self.pointer.calibrate()
        elif action == "pointer.toggle":
            self.pointer.enabled = not self.pointer.enabled
            log.info(f"pointer enabled={self.pointer.enabled}")
        elif action in macos.MEDIA_KEY_CODES:
            macos.post_media_key(macos.MEDIA_KEY_CODES[action])
        elif action in macos.SPACES_KEYCODES:
            macos.switch_space(action)
        elif action.startswith("shell:"):
            subprocess.Popen(action[len("shell:"):], shell=True)
        elif host := self.host_action(action):
            host(action)
        else:
            log.warning(f"unknown action {action}")

    def host_action(self, action):
        return next((fn for prefix, fn in self.actions.items() if action.startswith(prefix)), None)

    def release_action(self, action):
        if not action or self.dry_run:
            return
        log.info(f"release {action}")
        if action.startswith("key."):
            keycode, mods = macos.parse_combo(action[len("key."):])
            macos.post_key(keycode, mods, False)
        elif action.startswith("mouse.") and action.endswith("_down"):
            flags, mods, what = macos.parse_mouse(action[len("mouse."):])
            macos.post_mouse_button(what[:-len("_down")], False, flags)
            macos.post_modifiers(mods, False)
            if flags:
                macos.post_flags_reset()
            self.left_down = False
            self.mouse_flags = 0

    def release_all(self):
        if self.held_action:
            self.release_action(self.held_action)
        for entry in self.pressed.values():
            if isinstance(entry, str):
                self.release_action(entry)
        self.pressed.clear()
        self.held = self.held_action = self.pending = None
        if not self.dry_run:
            macos.post_flags_reset()

    def button_down(self, name, now):
        entry = self.buttons_cfg.get(name)
        if entry is None:
            return
        self.pressed[name] = entry
        if isinstance(entry, dict) and "repeat" in entry:
            self.tap(entry.get("down"))
            self.held = (name, entry, now + entry["repeat"].get("delay", 0.35), 0)
            return
        if isinstance(entry, dict) and ("hold" in entry or "press" in entry or "move" in entry):
            after = entry["hold"].get("after", 0.25) if "hold" in entry else float("inf")
            self.pending = (name, entry, now + after, 0.0)
            return
        self.run_action(entry.get("down") if isinstance(entry, dict) else entry)

    def button_up(self, name):
        entry = self.pressed.pop(name, None)
        if entry is None:
            return
        if self.pending is not None and self.pending[0] == name:
            self.pending = None
            self.tap(entry.get("press"))
            return
        if self.held is not None and self.held[0] == name:
            if self.held[2] is None:
                self.release_action(self.held_action)
                self.held_action = None
                if up := (entry.get("hold") or {}).get("up"):
                    self.run_action(up)
            self.held = None
            return
        if isinstance(entry, dict):
            self.run_action(entry.get("up"))
        else:
            self.release_action(entry)

    def wheel(self, delta):
        if delta == 0:
            return
        if self.wheel_cfg.get("action", "scroll") == "scroll":
            lines = self.wheel_cfg.get("lines", 3) * delta
            if self.wheel_cfg.get("invert"):
                lines = -lines
            log.debug(f"scroll {lines}")
            if not self.dry_run:
                macos.post_scroll(lines)
        else:
            key = "up_action" if delta > 0 else "down_action"
            self.run_action(self.wheel_cfg.get(key))
