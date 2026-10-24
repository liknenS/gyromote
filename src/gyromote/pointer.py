import json
import logging
from pathlib import Path

log = logging.getLogger("gyromote")

DEFAULT_CALIBRATION_PATH = Path.home() / "Library/Application Support/gyromote/calibration.json"


class Pointer:
    AXES = {"gyro_x": 0, "gyro_y": 1, "gyro_z": 2}

    def __init__(self, cfg, calibration_path=None, emit=lambda event: None, toast=lambda text: None):
        self.cfg = cfg
        self.calibration_path = Path(calibration_path or DEFAULT_CALIBRATION_PATH)
        self.emit = emit
        self.toast = toast
        self.enabled = cfg.get("enabled", True)
        self.bias = [0.0, 0.0, 0.0]
        self.smoothed = [0.0, 0.0]
        self.calib_samples = None
        if self.calibration_path.exists():
            self.bias = json.loads(self.calibration_path.read_text())["gyro_bias"]
            log.info(f"gyro bias loaded {self.bias}")
        else:
            log.info(f"no {self.calibration_path}: gyro bias is zero; put the remote down and run pointer.calibrate")

    def calibrate(self):
        self.calib_samples = []
        self.emit({"type": "calibration", "state": "start"})
        self.toast("calibrating: keep the remote still")

    def _collect(self, gyro):
        self.calib_samples.append(gyro)
        n = self.cfg.get("calibration_samples", 100)
        if len(self.calib_samples) < n:
            return
        self.bias = [sum(s[i] for s in self.calib_samples) / n for i in range(3)]
        self.calib_samples = None
        self.smoothed = [0.0, 0.0]
        self.calibration_path.parent.mkdir(parents=True, exist_ok=True)
        self.calibration_path.write_text(json.dumps({"gyro_bias": self.bias}))
        log.info(f"gyro bias calibrated {self.bias}")
        self.emit({"type": "calibration", "state": "done", "bias": list(self.bias)})
        self.toast("calibration done")

    def update(self, gyro, hold_active):
        if self.calib_samples is not None:
            self._collect(gyro)
            return None
        if not self.enabled:
            return None
        if self.cfg.get("mode", "always") == "hold" and not hold_active:
            return None

        dead_zone = self.cfg.get("dead_zone", 40)
        smoothing = self.cfg.get("smoothing", 0.5)
        acceleration = self.cfg.get("acceleration", 1.0)
        xi = self.AXES[self.cfg.get("axis_x", "gyro_z")]
        yi = self.AXES[self.cfg.get("axis_y", "gyro_x")]
        raw_x = gyro[xi] - self.bias[xi]
        raw_y = gyro[yi] - self.bias[yi]
        raw_x = raw_x if abs(raw_x) >= dead_zone else 0.0
        raw_y = raw_y if abs(raw_y) >= dead_zone else 0.0
        self.smoothed[0] = smoothing * self.smoothed[0] + (1 - smoothing) * raw_x
        self.smoothed[1] = smoothing * self.smoothed[1] + (1 - smoothing) * raw_y

        signed_x = self._accelerate(self.smoothed[0], acceleration)
        signed_y = self._accelerate(self.smoothed[1], acceleration)
        if self.cfg.get("invert_x"):
            signed_x = -signed_x
        if self.cfg.get("invert_y"):
            signed_y = -signed_y
        sensitivity = self.cfg.get("sensitivity", 0.02)
        return signed_x * sensitivity, signed_y * sensitivity

    @staticmethod
    def _accelerate(value, exponent):
        if exponent == 1.0 or value == 0.0:
            return value
        magnitude = abs(value) ** exponent
        return magnitude if value > 0 else -magnitude
