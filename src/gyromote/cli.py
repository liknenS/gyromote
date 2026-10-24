import argparse
import json
import logging
import os
import signal
import statistics
import sys
import time
from pathlib import Path

from . import __version__, macos
from .config import ConfigError, load_config
from .pointer import DEFAULT_CALIBRATION_PATH, Pointer
from .remote import Remote
from .report import MIN_REPORT_LEN, PID, VID, button_name, decode, open_device, read_report


def _open_or_exit(vid, pid):
    dev = open_device(vid, pid)
    if dev is None:
        sys.exit(f"remote {vid:04x}:{pid:04x} not found (paired and connected? see docs/pairing.md)")
    return dev


def _frames(dev, hz):
    prev = None
    while True:
        raw = read_report(dev)
        if len(raw) >= MIN_REPORT_LEN:
            r = decode(raw)
            if r.tick != prev:
                prev = r.tick
                yield raw, r
        time.sleep(1 / hz)


def cmd_run(args):
    try:
        cfg = load_config(args.config) if args.config else {}
    except (OSError, ConfigError) as e:
        sys.exit(str(e))

    def on_event(event):
        if event["type"] == "accessibility" and event.get("trusted"):
            os.execv(sys.executable, [sys.executable] + sys.argv)
        if event["type"] != "pointer":
            print(json.dumps(event), flush=True)

    try:
        remote = Remote(cfg, on_event=on_event, calibration_path=args.calibration, flags_path=args.flags,
                        dry_run=args.dry_run)
    except ConfigError as e:
        sys.exit(f"{args.config}: {e}")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        remote.run()
    except KeyboardInterrupt:
        pass


def cmd_monitor(args):
    dev = _open_or_exit(args.vid, args.pid)
    t0 = time.monotonic()
    try:
        for raw, r in _frames(dev, args.hz):
            if args.raw:
                print(f"{time.monotonic() - t0:7.2f}s {raw.hex(' ').upper()}", flush=True)
            else:
                print(f"{time.monotonic() - t0:7.2f}s tick={r.tick:3d} b1=0x{raw[1]:02X} gyro={r.gyro} accel={r.accel} "
                      f"button={button_name(r.button) if r.button else '-'} wheel={r.wheel:+d}", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()


def cmd_calibrate(args):
    dev = _open_or_exit(args.vid, args.pid)
    pointer = Pointer({"calibration_samples": args.samples}, args.calibration, toast=print)
    pointer.calibrate()
    try:
        for _, r in _frames(dev, 50):
            pointer.update(r.gyro, False)
            if pointer.calib_samples is None:
                break
    finally:
        dev.close()
    print(f"gyro bias {pointer.bias} -> {pointer.calibration_path}")


def cmd_doctor(args):
    ok = True
    found = open_device(args.vid, args.pid)
    print(f"remote {args.vid:04x}:{args.pid:04x}: {'found' if found else 'NOT FOUND'}")
    ok &= found is not None
    trusted = macos.accessibility_trusted()
    print(f"accessibility: {'granted' if trusted else 'NOT GRANTED (needed to post input events)'}")
    ok &= trusted
    calibration = Path(args.calibration or DEFAULT_CALIBRATION_PATH)
    print(f"calibration: {calibration if calibration.exists() else 'none (gyro bias is zero)'}")
    if found:
        fresh, latencies, prev, t0 = 0, [], None, time.monotonic()
        try:
            while time.monotonic() - t0 < 2.0:
                t = time.monotonic()
                raw = read_report(found)
                latencies.append(time.monotonic() - t)
                if len(raw) >= MIN_REPORT_LEN and raw[2] != prev:
                    prev, fresh = raw[2], fresh + 1
        except Exception as e:
            print(f"read error: {e}")
            ok = False
        finally:
            found.close()
        if latencies:
            print(f"polling: {fresh / 2.0:.0f} fresh frames/s, GET_REPORT p50 {statistics.median(latencies) * 1000:.1f} ms")
    sys.exit(0 if ok else 1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="gyromote", description="LG Magic Remote MR25GA as a gyro mouse and button pad on macOS")
    p.add_argument("--version", action="version", version=f"gyromote {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="log every button, action and release")
    sub = p.add_subparsers(dest="cmd", required=True)

    def device_args(sp):
        sp.add_argument("--vid", type=lambda x: int(x, 0), default=VID)
        sp.add_argument("--pid", type=lambda x: int(x, 0), default=PID)

    run = sub.add_parser("run", help="drive the cursor, keys and actions from a config")
    run.add_argument("--config", type=Path, help="YAML config (see examples/config.yaml)")
    run.add_argument("--dry-run", action="store_true", help="log actions, post no input events")
    run.add_argument("--calibration", type=Path, help=f"gyro bias file (default {DEFAULT_CALIBRATION_PATH})")
    run.add_argument("--flags", type=Path, help="persist flag state in this JSON file")
    run.set_defaults(fn=cmd_run)

    mon = sub.add_parser("monitor", help="print decoded 0xFD reports")
    device_args(mon)
    mon.add_argument("--hz", type=float, default=50)
    mon.add_argument("--raw", action="store_true", help="print raw report bytes")
    mon.set_defaults(fn=cmd_monitor)

    cal = sub.add_parser("calibrate", help="measure gyro bias with the remote lying still")
    device_args(cal)
    cal.add_argument("--samples", type=int, default=100)
    cal.add_argument("--calibration", type=Path, help=f"where to write (default {DEFAULT_CALIBRATION_PATH})")
    cal.set_defaults(fn=cmd_calibrate)

    doc = sub.add_parser("doctor", help="check the remote, permissions and polling rate")
    device_args(doc)
    doc.add_argument("--calibration", type=Path)
    doc.set_defaults(fn=cmd_doctor)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(message)s", stream=sys.stderr)
    args.fn(args)


if __name__ == "__main__":
    main()
