# Changelog

All notable changes. Versions follow SemVer: a change to the config schema or the event schema is a
major version.

## 0.1.0 (unreleased)

First release, extracted from a private home-automation daemon where this code ran daily.

- Transport: hidapi `GET_REPORT 0xFD` polling with adaptive rate (`poll_hz`, `poll_hz_idle`,
  `poll_boost_seconds`), tick de-duplication, reconnect, release of a held button when the remote
  drops off for 8 s (`lost: true`).
- Gyro pointer: bias calibration, dead zone, smoothing, power-curve acceleration, `always`/`hold`
  modes, idle-off, wake button, press freeze.
- Buttons: plain actions, `{down, up}`, press/move/hold gestures with per-app hold, auto-repeat with
  action switch, wheel as scroll or as two actions, flags that overlay buttons and wheel.
- Actions: `key.*`, `mouse.*`, `media.*`, `spaces.*`, `pointer.*`, `flag.*`, `shell:`, `none`, plus
  host-defined prefixes.
- Library API `Remote` with `on_event`, `actions`, `intercept`, `on_toast`, `calibration_path`,
  `flags_path`, `dry_run`; CLI `run`, `monitor`, `calibrate`, `doctor`.

Differences from the daemon this was extracted from:

- Added `hold.through_intercept`: arms a hold while the host intercepts the button. The daemon
  decided this by a hard-coded action prefix.
- Added: `stop()` (and interpreter exit) releases held keys, mouse buttons and modifiers, then
  clears modifier flags, so a crash or restart in the middle of an Alt-drag does not leave Alt or
  the mouse button stuck. `gyromote run` turns SIGTERM into a clean stop for this.
- Added: config validation at load. Unknown actions, keys, modifiers, mouse buttons and flag names
  raise `ConfigError` with the key path instead of a runtime log line. `load_config` refuses a
  world-writable file.
- Added: `calibration` and `accessibility` events. The library no longer restarts its host process
  when Accessibility is granted; the CLI does.
- Changed: calibration lives at an explicit path, default
  `~/Library/Application Support/gyromote/calibration.json`. Without the file the bias is zero, as
  before.
- Changed: `--dry-run` also skips the Accessibility prompt and posts no pointer motion.
- Changed: logging goes to the `gyromote` logger; toasts are English.
