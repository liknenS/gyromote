# gyromote

Use an **LG Magic Remote MR25GA** as a gyro mouse and a programmable button pad on macOS.

**Read this first: macOS caps the remote at about 66 reads per second, and the scroll wheel loses
about one notch in three.** macOS never delivers this remote's HID reports as push notifications,
so gyromote polls them with `GET_REPORT`. One poll takes one BLE connection interval (15 ms), which
caps polling at about 66 Hz. A wheel notch lives in a single 10 ms frame, so polling catches about
two thirds of them. This is a limit of macOS, not a bug in gyromote, and no setting fixes it. The
cursor, the buttons and push-to-talk work fine at this rate. See [docs/protocol.md](docs/protocol.md).

How it was built: <https://nikitenok.dev/blog/lg-magic-remote/>

Not affiliated with or endorsed by LG Electronics. "LG" and "Magic Remote" are used only to name
the hardware this works with.

## Safety

- **gyromote never talks to the remote's GATT services.** It only opens the HID collection
  through hidapi and reads input report `0xFD`. Do not write to the remote's vendor service
  `0000D0FF-…` (Realtek OTA, characteristics FFD1/FFD8/FFF2) or to A002 in `0000D1FF-…` with
  other tools. A blind write there can put the remote into firmware-update mode and brick it.
- **Accessibility gives the process full control of your input.** gyromote needs it to post
  keyboard, mouse and scroll events. Under launchd the grant goes to the Python binary itself (the
  interpreter of your venv), not to a terminal app. Use a dedicated venv for gyromote, so the
  binary you trust runs nothing else. **Input Monitoring is not needed**: the remote's only HID
  collection (Consumer Control) opens without it.
- **The config is trusted input.** A `shell:` action runs its command through `/bin/sh` as your
  user. Keep the config file writable only by you; `load_config` refuses a world-writable file.
  gyromote has no network or socket input of its own.

## Requirements

- macOS on Apple Silicon. Tested only on macOS 26 with Python 3.12; earlier macOS versions and
  Intel Macs are untested.
- Python 3.10 or newer.
- An MR25GA paired with the Mac: see [docs/pairing.md](docs/pairing.md). The remote does not
  show up in the Bluetooth settings window, so pairing takes a few extra steps.

## Install

```
python3 -m venv ~/.venvs/gyromote
~/.venvs/gyromote/bin/pip install "gyromote @ git+https://github.com/liknenS/gyromote.git@v0.1.0"
~/.venvs/gyromote/bin/gyromote doctor
```

`doctor` checks that the remote is visible, that Accessibility is granted, and how fast polling
actually runs.

## Command line

```
gyromote run --config examples/config.yaml            # drive the cursor and actions
gyromote run --config examples/config.yaml --dry-run  # log actions, post no input
gyromote monitor                                      # print decoded reports
gyromote calibrate                                    # measure gyro bias, remote lying still
gyromote doctor
```

`run` prints every event except pointer motion as a JSON line on stdout. `-v` before the
subcommand logs each button, action and release to stderr. When Accessibility is granted while
`run` is running, it restarts itself: macOS lets a process post input events only if it was
trusted at launch.

### Running at login

A LaunchAgent at `~/Library/LaunchAgents/dev.gyromote.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.gyromote</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/.venvs/gyromote/bin/python</string>
    <string>/Users/YOU/.venvs/gyromote/bin/gyromote</string>
    <string>run</string>
    <string>--config</string><string>/Users/YOU/.config/gyromote/config.yaml</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>/Users/YOU/Library/Logs/gyromote.log</string>
</dict>
</plist>
```

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.gyromote.plist
launchctl kickstart -k gui/$(id -u)/dev.gyromote    # restart after editing the config
```

On first start macOS shows the Accessibility prompt for that Python binary.

## Configuration

A full example with comments: [examples/config.yaml](examples/config.yaml). Button names:
[docs/buttons.md](docs/buttons.md).

| Key | Default | Meaning |
|---|---|---|
| `poll_hz` | 50 | polling rate while the cursor is on; the real ceiling is about 66 |
| `poll_hz_idle` | `poll_hz` | polling rate while the cursor is off |
| `poll_boost_seconds` | 2.0 | any button or wheel notch returns to `poll_hz` for this long |
| `vid`, `pid` | `0x005D`, `0x8762` | USB IDs the remote reports (Realtek RTL8762) |
| `repeat_delay`, `repeat_interval` | 0.4, 0.1 | timing of `state: repeat` button events |
| `pointer.*` | | see below |
| `buttons` | `{}` | button name → action or gesture |
| `wheel` | scroll, 3 lines | `action: scroll` (`lines`, `invert`) or `action: buttons` (`up_action`, `down_action`) |
| `flags` | `{}` | named switches that overlay `buttons` and `wheel` |

Pointer: `enabled`, `mode` (`always`, or `hold` with `hold_button`), `axis_x`/`axis_y`
(`gyro_x|gyro_y|gyro_z`, defaults `gyro_z`/`gyro_x`), `invert_x`/`invert_y`, `sensitivity`,
`dead_zone`, `smoothing`, `acceleration` (power curve exponent), `calibration_samples`,
`idle_off_seconds` (the cursor turns itself off after this long without motion), `wake_button`
(wakes the cursor without clicking), `press_freeze_seconds` (the cursor holds still right after a
press, so a click does not slip or turn into a drag).

### Actions

| Action | Effect |
|---|---|
| `key.<mods+key>` | keystroke, e.g. `key.escape`, `key.cmd+shift+4`, `key.alt+backspace`; mods `cmd shift alt opt ctrl`; ANSI key codes |
| `mouse.[mods+]left\|right\|middle_click` | click |
| `mouse.[mods+]left\|right\|middle_down` | press, released with the remote button; `mouse.alt+left_down` gives Alt-drag |
| `media.volume_up\|volume_down\|mute\|play_pause` | system media keys |
| `spaces.left\|right` | switch desktop (via System Events: Mission Control ignores synthetic Ctrl+arrow) |
| `pointer.toggle`, `pointer.calibrate` | cursor on/off, start gyro calibration |
| `flag.on:<name>`, `flag.off:<name>`, `flag.toggle:<name>` | switch a flag |
| `shell:<command>` | run a command (trusted input, see Safety) |
| `none` | nothing |

Unknown actions, keys, modifiers and flag names are rejected when the config is loaded.

### Button forms

```yaml
buttons:
  up: key.up                       # down on press, release on release
  mic: {down: "shell:...", up: "shell:..."}   # two independent actions
  wheel:
    press: mouse.left_click        # released before hold.after
    move: mouse.left_down          # cursor moved past move_threshold px: plain drag
    move_threshold: 8
    hold:
      after: 0.4                   # held still: hold.down, released with the button
      down: mouse.alt+left_down
      up: null                     # optional action after release
      apps: [com.apple.Terminal]   # hold.down only in these apps (bundle id), otherwise `move`
      through_intercept: false     # arm this hold even while the host intercepts the button
  netflix:
    down: key.backspace
    repeat: {delay: 0.35, interval: 0.07, switch_after: 6, then: key.alt+backspace, then_interval: 0.15}
```

The protocol reports one button at a time, so there are no chords.

### Flags

Each enabled flag overlays its own `buttons` and `wheel` on top of the base ones, in config order.
A flag with no overrides is still useful as a shared on/off switch that a host reads from events.
`flags_path` (`--flags`) keeps their state across restarts.

## Library

```python
from gyromote import Remote, load_config

remote = Remote(
    load_config("config.yaml"),
    on_event=print,                          # every event below, from the polling thread
    actions={"app:": lambda a: ...},         # your own action prefixes, matched by startswith
    intercept=lambda name: False,            # True = this button goes to you only, no action
    on_toast=print,                          # short user-facing notices
    calibration_path=None,                   # default ~/Library/Application Support/gyromote/calibration.json
    flags_path=None,                         # None = flags are not persisted
    dry_run=False,
)
remote.start()          # background thread; remote.run() blocks instead
remote.set_flag("slides", True)
remote.flags            # {"slides": True, ...}
remote.pointer_enabled = False
remote.calibrate()
remote.connected
remote.stop()           # releases held keys, mouse buttons and modifiers
```

`Remote()` validates the config, including your `actions` prefixes, and raises `ConfigError` with
the key path. `intercept(name)` gets a button name, or `"scroll"` for the wheel. An intercepted
button still produces events. With the cursor on, `wake_button` and the wheel always act as the
mouse and skip `intercept`.

### Events

```
{"type": "button", "name": "up", "code": "0x8040", "state": "down", "mouse": false}
{"type": "button", "name": "up", "code": "0x8040", "state": "repeat"}
{"type": "button", "name": "up", "code": "0x8040", "state": "up"}
{"type": "button", "name": "mic", "code": "0x808B", "state": "up", "lost": true}
{"type": "wheel", "delta": 1, "mouse": true}
{"type": "pointer", "dx": 1.2, "dy": -0.4}
{"type": "device", "state": "connected"}
{"type": "flag", "name": "slides", "on": true, "flags": {"slides": true}}
{"type": "calibration", "state": "start"}
{"type": "calibration", "state": "done", "bias": [12.3, -4.0, 7.9]}
{"type": "accessibility", "trusted": true}
```

- `mouse: true` on a button `down` or a wheel event means it acted as the mouse (the cursor was on
  and it is the `wake_button` / the wheel).
- `repeat` follows `down` after `repeat_delay`, every `repeat_interval`, until `up`.
- `lost: true`: the remote dropped off with a button held and did not come back within 8 s, so
  gyromote released the button on its behalf. Without this a push-to-talk would stay open.
- `accessibility` arrives once, when the grant appears while running. Input events start working
  only after the process restarts; the library does not restart its host.

The event schema is part of the public API: a change to it is a major version bump.

## Limitations

- About 66 Hz polling and about two thirds of wheel notches (see the top).
- The cursor stays on the main display.
- Gyro bias comes only from `calibrate`; without a calibration file it is zero. There is no
  automatic drift compensation.
- The remote's microphone is not reachable on macOS (see [docs/protocol.md](docs/protocol.md)).
- The accelerometer is decoded but not used.

## Prior art

- [brainrom/lg-magic](https://github.com/brainrom/lg-magic): Linux kernel driver for the MR20.
- [retsyx/amity](https://github.com/retsyx/amity): Raspberry Pi HDMI-CEC hub that supports MR19/MR20 remotes.
- [Cathwyler/MagicRemoteService](https://github.com/Cathwyler/MagicRemoteService): an LG webOS app that turns the remote into a PC mouse via the TV.

gyromote contains no code from these projects. The report layout and button codes were measured
again on a live MR25GA.

## License

MIT, see [LICENSE](LICENSE).
