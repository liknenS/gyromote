import atexit
import json
import logging
import threading
import time
from pathlib import Path

from . import macos
from .config import validate_config
from .pointer import Pointer
from .report import MIN_REPORT_LEN, PID, VID, button_name, decode, open_device, read_report
from .router import Router

log = logging.getLogger("gyromote")

LOST_UP_S = 8.0
RETRY_S = 3.0
READ_ERROR_PAUSE_S = 2.0
ABSENT_LOG_S = 600.0


class Remote:
    def __init__(self, config, *, on_event=lambda event: None, actions=None, intercept=lambda name: False,
                 on_toast=print, calibration_path=None, flags_path=None, dry_run=False):
        validate_config(config, actions or ())
        self.cfg = config
        self.on_event = on_event
        self.intercept = intercept
        self.on_toast = on_toast
        self.flags_path = Path(flags_path) if flags_path else None
        self.dry_run = dry_run
        self.connected = False
        self.pointer = Pointer(config.get("pointer", {}) or {}, calibration_path, emit=on_event, toast=on_toast)
        self.router = Router(config, self.pointer, actions=actions, dry_run=dry_run)
        saved = self._load_flags()
        self.router.flags.update({k: bool(v) for k, v in saved.items() if k in self.router.flag_cfg})
        self.router.apply_flags()
        self.router.on_flag = self._on_flag
        self._stop = threading.Event()
        self._thread = None

    @property
    def flags(self):
        return dict(self.router.flags)

    def set_flag(self, name, on):
        self.router.set_flag(name, on)

    def calibrate(self):
        self.pointer.calibrate()

    @property
    def pointer_enabled(self):
        return self.pointer.enabled

    @pointer_enabled.setter
    def pointer_enabled(self, on):
        self.pointer.enabled = bool(on)

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="gyromote", daemon=True)
        self._thread.start()
        atexit.register(self.stop)

    def stop(self, timeout=3.0):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)
        atexit.unregister(self.stop)

    def run(self):
        self._stop.clear()
        self._loop()

    def _load_flags(self):
        if not self.flags_path:
            return {}
        try:
            data = json.loads(self.flags_path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_flags(self):
        if not self.flags_path:
            return
        try:
            self.flags_path.parent.mkdir(parents=True, exist_ok=True)
            self.flags_path.write_text(json.dumps(self.router.flags))
        except OSError as e:
            log.warning(f"could not save flags: {e}")

    def _on_flag(self, name, on):
        self._save_flags()
        self.on_event({"type": "flag", "name": name, "on": on, "flags": dict(self.router.flags)})
        title = (self.router.flag_cfg.get(name) or {}).get("title", name)
        self.on_toast(f"{title}: {'on' if on else 'off'}")

    def _sleep_until(self, deadline):
        self._stop.wait(max(0.0, deadline - time.monotonic()))

    def _loop(self):
        self._dev = None
        try:
            self._poll()
        finally:
            self.router.release_all()
            if self._dev is not None:
                self._dev.close()
                self._dev = None

    def _poll(self):
        cfg = self.cfg
        pointer, router, emit = self.pointer, self.router, self.on_event
        hz = cfg.get("poll_hz", 50)
        idle_hz = cfg.get("poll_hz_idle", hz)
        boost_seconds = cfg.get("poll_boost_seconds", 2.0)
        vid = cfg.get("vid", VID)
        pid = cfg.get("pid", PID)
        pointer_cfg = cfg.get("pointer", {}) or {}
        hold_button = pointer_cfg.get("hold_button")
        repeat_delay = cfg.get("repeat_delay", 0.4)
        repeat_interval = cfg.get("repeat_interval", 0.1)

        ax_trusted = True if self.dry_run else macos.request_accessibility()
        ax_checked = time.monotonic()
        log.info(f"vid=0x{vid:04X} pid=0x{pid:04X} hz={hz} pointer_mode={pointer_cfg.get('mode', 'always')}")

        prev_tick = None
        prev_button_code = 0
        current_button_name = None
        boost_until = 0.0
        next_poll = time.monotonic()
        idle_off = pointer_cfg.get("idle_off_seconds", 30)
        wake_button = pointer_cfg.get("wake_button", "wheel")
        last_motion = time.monotonic()
        press_freeze = pointer_cfg.get("press_freeze_seconds", 0.15)
        frozen_until = 0.0
        repeat_press = None
        absent_logged = float("-inf")
        lost_at = None

        while not self._stop.is_set():
            if self._dev is None:
                self._dev = open_device(vid, pid)
                if self._dev is None:
                    now = time.monotonic()
                    if prev_button_code and lost_at is not None and now - lost_at >= LOST_UP_S:
                        # the remote dropped with a button held and stayed away: release it, or a push-to-talk stays open
                        name = button_name(prev_button_code)
                        log.info(f"button_up {name} (remote lost)")
                        emit({"type": "button", "name": name, "code": f"0x{prev_button_code:04X}", "state": "up", "lost": True})
                        router.button_up(name)
                        prev_button_code, current_button_name, repeat_press = 0, None, None
                    if self.connected or now - absent_logged >= ABSENT_LOG_S:
                        log.info("device open failed, retry")
                        absent_logged = now
                    if self.connected:
                        self.connected = False
                        emit({"type": "device", "state": "disconnected"})
                    if self._stop.wait(RETRY_S):
                        break
                    continue
                log.info("device connected")
                self.connected = True
                emit({"type": "device", "state": "connected"})
                prev_tick = None

            try:
                report = read_report(self._dev)
            except Exception as exc:
                log.info(f"read error ({exc}), reconnecting")
                self._dev.close()
                self._dev = None
                lost_at = time.monotonic()
                if self._stop.wait(READ_ERROR_PAUSE_S):
                    break
                continue

            now = time.monotonic()
            router.tick(now)
            active = pointer.enabled or now < boost_until
            next_poll += 1.0 / (hz if active else idle_hz)
            if next_poll < now:
                next_poll = now

            if len(report) < MIN_REPORT_LEN:
                self._sleep_until(next_poll)
                continue

            r = decode(report)
            if r.tick == prev_tick:
                self._sleep_until(next_poll)
                continue
            ticks_elapsed = 1 if prev_tick is None else min((r.tick - prev_tick) % 256, 10)
            prev_tick = r.tick

            # CGEvent starts working only in a new process after the Accessibility grant: the host restarts itself
            if not ax_trusted and now - ax_checked > 2.0:
                ax_checked = now
                if macos.accessibility_trusted():
                    ax_trusted = True
                    log.info("Accessibility granted")
                    emit({"type": "accessibility", "trusted": True})

            if r.button != prev_button_code or r.wheel != 0:
                boost_until = now + boost_seconds

            if r.button != prev_button_code:
                if prev_button_code != 0:
                    name = button_name(prev_button_code)
                    log.info(f"button_up {name}")
                    emit({"type": "button", "name": name, "code": f"0x{prev_button_code:04X}", "state": "up"})
                    repeat_press = None
                    router.button_up(name)
                    if current_button_name == name:
                        current_button_name = None
                if r.button != 0:
                    name = button_name(r.button)
                    last_motion = now
                    frozen_until = now + press_freeze
                    grabbed = self.intercept(name) and not (pointer.enabled and name == wake_button)
                    log.info(f"button_down {name}" + (" (intercepted)" if grabbed else ""))
                    emit({"type": "button", "name": name, "code": f"0x{r.button:04X}", "state": "down", "mouse": name == wake_button and pointer.enabled})
                    repeat_press = [name, f"0x{r.button:04X}", now + repeat_delay]
                    if grabbed:
                        router.arm_hold_only(name, now)
                    elif name == wake_button and not pointer.enabled:
                        pointer.enabled = True
                        last_motion = now
                        log.info("pointer woke")
                    else:
                        router.button_down(name, now)
                    current_button_name = name
                prev_button_code = r.button

            if repeat_press is not None and now >= repeat_press[2]:
                emit({"type": "button", "name": repeat_press[0], "code": repeat_press[1], "state": "repeat"})
                repeat_press[2] = now + repeat_interval

            if r.wheel != 0:
                emit({"type": "wheel", "delta": r.wheel, "mouse": pointer.enabled})
                if pointer.enabled or not self.intercept("scroll"):
                    router.wheel(r.wheel)

            move = pointer.update(r.gyro, current_button_name == hold_button)
            if move is not None and move != (0.0, 0.0):
                last_motion = now
            if pointer.enabled and now - last_motion > idle_off:
                pointer.enabled = False
                log.info("pointer idle, off")
            # the press jolt and the smoothing tail after aiming would shift the click and add up to the drag threshold
            if move is not None and now >= frozen_until:
                dx, dy = (v * ticks_elapsed / 2 for v in move)
                if (dx, dy) != (0.0, 0.0):
                    emit({"type": "pointer", "dx": round(dx, 2), "dy": round(dy, 2)})
                router.pointer_moved(dx, dy)
                if not self.dry_run:
                    macos.post_pointer_move(dx, dy, router.left_down, router.mouse_flags)

            self._sleep_until(next_poll)

