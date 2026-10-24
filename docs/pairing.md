# Pairing the MR25GA with a Mac

The remote does not appear in System Settings > Bluetooth: its advertisement carries no HID
service and no appearance, and that window lists only devices that announce one. Pairing therefore
has to be started by a program that connects to the remote. After that macOS takes over.

**gyromote does not ship a pairing tool yet.** This page describes what happens, so you can do it
with a BLE central of your choice. Whatever you use, it only needs to *connect*: no service
discovery, no reads, no writes, and above all no writes to the OTA service (see
[protocol.md](protocol.md)).

## What happens

1. **Unpair the remote from its TV**: hold **Home + Back** for more than 5 seconds until the LED
   blinks. The remote then advertises as `LGE MR25GA`.
2. **Connect to it** from a CoreBluetooth central, by name.
3. Right after the connection the remote sends an SMP Security Request (bonding, no MITM).
   bluetoothd discovers the HID service and shows a Just Works pairing dialog about 0.9 s after
   connect.
4. **Click Connect within about 1.5 s.** The remote drops the link about 2.7 s after connect if
   pairing has not completed (`Pairing failed … error 708` in the bluetoothd log), and a late click
   is rejected. Keep the mouse where the dialog appears before you start.
5. If you missed it, connect again. A connection by the CoreBluetooth peripheral identifier,
   without a scan, brings the dialog up faster.

## Check

```
system_profiler SPBluetoothDataType | grep -A4 LGE    # VID 0x005D, PID 0x8762
gyromote doctor                                        # remote found, polling rate
```

Once bonded, macOS keeps the remote connected by itself. The remote pairs with one host at a time:
while it is paired to the Mac, the TV does not see it.

## Notes

- The connecting app needs the Bluetooth permission. gyromote itself does not: it opens the HID
  collection that macOS publishes after pairing.
- Scripting the Connect click through System Events did not work: the dialog is not reachable that
  way.
