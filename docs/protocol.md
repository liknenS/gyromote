# MR25GA protocol on macOS

What is known about the LG Magic Remote MR25GA as macOS sees it. Everything below was measured on
a live remote paired with a Mac running macOS 26, unless marked otherwise.

## The device

- Advertised name `LGE MR25GA`. The advertisement carries no service UUIDs and appearance `0x0000`,
  which is why the macOS Bluetooth window never lists it (see [pairing.md](pairing.md)).
- PnP ID: VID `0x005D`, PID `0x8762`, i.e. a Realtek RTL8762 SoC. The Device Information
  strings are Realtek SDK defaults.
- BLE 4.2. Power is infrared only and produces no BLE report.
- After pairing, macOS publishes **one** HID collection: usage page `0x000C` (Consumer), usage
  `0x0001` (Consumer Control). No system driver attaches to it, so macOS itself generates no
  keyboard or mouse events from the remote. hidapi opens it without Input Monitoring.

### Report descriptor

```
05 0C 09 01 A1 01 85 FD 95 1E 75 08 15 00 26 FF 00 81 00 C0
05 0C 09 01 A1 01 85 F9 95 1E 75 08 15 00 26 FF 00 81 00 95 C8 75 08 15 00 26 FF 00 B1 00 C0
05 0C 09 01 A1 01 85 FE 95 7C 75 08 15 00 26 FF 00 81 00 C0
```

| Report ID | Kind | Declared size | Observed |
|---|---|---|---|
| `0xFD` | input | 30 bytes + ID | 20 bytes with ID; motion, buttons, wheel |
| `0xF9` | input + feature (200) | 30 bytes + ID | `GET_REPORT` always fails |
| `0xFE` | input | 124 bytes + ID | `GET_REPORT` always fails; the likely voice stream |

All three sit on the Consumer page, so macOS publishes them over Bluetooth. A vendor usage page
would be hidden from userspace on BLE.

## Report 0xFD

20 bytes including the ID, multi-byte fields big-endian.

| Offset | Size | Type | Field | Confidence |
|---|---|---|---|---|
| 0 | 1 | | report ID `0xFD` | confirmed |
| 1 | 1 | | varies 0xB9–0xD1 with motion; not a counter | unknown |
| 2 | 1 | u8 | tick, 100 per second, wraps at 256 | confirmed |
| 3 | 1 | | `0xFD` (rarely `0xFE`) | constant |
| 4 | 1 | | `0x02` | constant |
| 5–10 | 2×3 | i16 | gyro X, Y, Z | strong |
| 11–16 | 2×3 | i16 | accel X, Y, Z; magnitude at rest ≈ 4100 = 1 g | confirmed |
| 17–18 | 2 | u16 | button code, `0x0000` = none | confirmed |
| 19 | 1 | i8 | wheel, ±1 per notch, 0 otherwise | confirmed |

Axes, held like a pointer: turning left/right (yaw) shows on **gyro Z**, tilting up/down (pitch)
on **gyro X**. Screen `dx = +gyro_z`, `dy = +gyro_x` moves the cursor the way the remote points.
These are gyromote's defaults.

Only one button code fits in the report, so the remote cannot report chords. Codes are listed in
[buttons.md](buttons.md).

## Why polling, and why 66 Hz

The remote does send `0xFD` as BLE notifications, about 100 per second, once the CCCD for that
report is enabled. An Android HCI capture shows exactly that stream.

On macOS the notifications never reach userspace: neither hidapi nor IOHIDManager sees a single
push report. The reason is visible in bluetoothd's own GATT state dump
(`log show --predicate 'subsystem == "com.apple.bluetooth"'`): all three input reports have
`Client Configuration [ none ]`, so macOS never enabled notifications. CoreBluetooth hides the
HID service from apps, so a third-party process cannot write that CCCD either.

What does work is `GET_REPORT` on `0xFD`: the remote answers with its current frame. bluetoothd
holds the connection at a 15 ms interval (`switchLEHIDsConnectionInterval … current 15.00 ms`),
and one `GET_REPORT` takes one interval, so the ceiling is about 66 reads per second (p50 ≈ 14 ms).
The low-latency mode bluetoothd uses for BLE mice is chosen by appearance, and the remote's
appearance is zero.

Consequences:

- The cursor gets about 60 fresh frames per second, which feels smooth. The tick in byte 2 tells
  how many 10 ms frames were skipped between polls; gyromote scales motion by it.
- A wheel notch is `±1` in exactly one 10 ms frame, so polling catches about two thirds of them.
- A full-rate stream on a Mac needs another BLE host (Linux/BlueZ, or a custom central on a
  microcontroller) bridged to the Mac.

## Microphone

Not available on macOS. `GET_REPORT` for `0xFE` and `0xF9` fails at rest and with the mic button
held, and no notifications arrive on the vendor service while talking. The voice transport is most
likely `0xFE` notifications, which nobody enables on macOS. The mic button itself (`0x808B`) is an
ordinary code in `0xFD` and stays set while held, so it works as push-to-talk for any other
microphone.

## GATT services visible to CoreBluetooth

| Service | Characteristics | Notes |
|---|---|---|
| `180F` Battery | `2A19` read, notify | percent |
| `180A` Device Information | strings, PnP ID `2A50` | Realtek defaults |
| `1813` Scan Parameters | standard | |
| `0000D1FF-3C17-D293-8E48-14FE2E4DA212` | `A001` write-no-response + notify, `A002` write | Realtek vendor space; candidate private channel |
| `0000D0FF-3C17-D293-8E48-14FE2E4DA212` | `FFD1` w, `FFD2`–`FFD5` r, `FFD8` w, `FFF1` r, `FFF2` w, `FFE0`–`FFE2` r | **Realtek OTA / firmware update** |
| `1812` HID | hidden from apps | bluetoothd owns it |

**Never write to `A002`, `FFD1`, `FFD8` or `FFF2`.** A blind write to the OTA service can put the
remote into firmware-update mode. gyromote uses none of these services: it only reads `0xFD`
through the HID collection.

## Related work

The MR20 Linux driver [brainrom/lg-magic](https://github.com/brainrom/lg-magic) uses the same
`0xFD` layout for gyro, accel, buttons and wheel, and the button codes checked so far match the
MR20. Its documentation and one issue disagree on bytes 1–3; on the MR25GA byte 2 is the tick.
gyromote shares no code with it.
