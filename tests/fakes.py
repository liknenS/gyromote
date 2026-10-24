import struct
import time

from gyromote.report import REPORT_ID


def frame(tick, button=0, wheel=0, gyro=(0, 0, 0), accel=(0, 0, 0)):
    return (bytes([REPORT_ID, 0xC0, tick % 256, 0xFD, 0x02]) + struct.pack(">hhh", *gyro)
            + struct.pack(">hhh", *accel) + struct.pack(">H", button) + struct.pack("b", wheel))


class Dev:
    """Serves reports in order; then repeats the last one, or raises like a dropped link."""

    def __init__(self, reports, then="error"):
        self.reports, self.then, self.last, self.closed, self.tick = list(reports), then, None, False, 0

    def get_input_report(self, rid, size):
        if self.reports:
            self.last = self.reports.pop(0)
            return self.last
        if self.then == "error" or self.last is None:
            raise OSError("read error")
        self.tick += 1
        return self.last[:2] + bytes([(self.last[2] + self.tick) % 256]) + self.last[3:]

    def close(self):
        self.closed = True


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()
