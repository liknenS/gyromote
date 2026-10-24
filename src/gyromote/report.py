import struct
from dataclasses import dataclass

import hid

VID = 0x005D
PID = 0x8762
REPORT_ID = 0xFD
REPORT_SIZE = 31
MIN_REPORT_LEN = 20

BUTTONS = {
    0x8040: "up", 0x8041: "down", 0x8006: "right", 0x8007: "left",
    0x8044: "wheel", 0x8028: "back", 0x807C: "home", 0x8043: "settings",
    0x8002: "vol_up", 0x8003: "vol_down", 0x808B: "mic",
    0x8000: "ch_up", 0x8001: "ch_down", 0x8045: "more",
    0x8029: "help", 0x80A1: "dashboard", 0x80AB: "guide",
    0x8056: "netflix", 0x805C: "prime", 0x8031: "disney", 0x8049: "rakuten",
    0x8048: "lg_channels", 0x800C: "alexa",
}


@dataclass(frozen=True)
class Report:
    tick: int
    gyro: tuple[int, int, int]
    accel: tuple[int, int, int]
    button: int
    wheel: int


def decode(raw: bytes) -> Report:
    return Report(
        tick=raw[2],
        gyro=struct.unpack(">hhh", raw[5:11]),
        accel=struct.unpack(">hhh", raw[11:17]),
        button=struct.unpack(">H", raw[17:19])[0],
        wheel=struct.unpack("b", raw[19:20])[0],
    )


def button_name(code: int) -> str:
    return BUTTONS.get(code, f"0x{code:04X}")


def open_device(vid: int = VID, pid: int = PID):
    try:
        matches = hid.enumerate(vid, pid)
        if not matches:
            return None
        dev = hid.device()
        dev.open_path(matches[0]["path"])
        return dev
    except Exception:
        return None


def read_report(dev) -> bytes:
    # macOS never delivers this remote's input reports as push (bluetoothd leaves the CCCD unset); GET_REPORT is the only path
    return bytes(dev.get_input_report(REPORT_ID, REPORT_SIZE))
