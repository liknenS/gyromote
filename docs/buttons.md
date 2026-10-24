# Buttons

Codes are the `u16` at bytes 17–18 of report `0xFD`. Every one was confirmed by pressing it on a
live MR25GA. The name is what gyromote uses in the config and in events. An unknown code is named
by its hex value, e.g. `0x803E`.

| Name | Code | Key on the remote | Notes |
|---|---|---|---|
| `up` | `0x8040` | ▲ | |
| `down` | `0x8041` | ▼ | |
| `left` | `0x8007` | ◀ | |
| `right` | `0x8006` | ▶ | |
| `wheel` | `0x8044` | wheel press (OK) | default `wake_button` |
| `back` | `0x8028` | Back | Home + Back held 5 s unpairs the remote from the TV |
| `home` | `0x807C` | Home | |
| `dashboard` | `0x80A1` | Home Dashboard (house with a circle) | |
| `settings` | `0x8043` | Settings (gear) | |
| `vol_up` | `0x8002` | Volume + | |
| `vol_down` | `0x8003` | Volume − | holding it is how a TV mutes; there is no mute code |
| `ch_up` | `0x8000` | Channel + | |
| `ch_down` | `0x8001` | Channel − | |
| `mic` | `0x808B` | Microphone | code stays set while held; the audio itself is not reachable on macOS |
| `more` | `0x8045` | 123 ••• | long press sends the same code |
| `help` | `0x8029` | ? | |
| `guide` | `0x80AB` | Guide | long press sends the same code |
| `netflix` | `0x8056` | Netflix | |
| `prime` | `0x805C` | prime video | |
| `disney` | `0x8031` | Disney+ | |
| `rakuten` | `0x8049` | Rakuten TV | |
| `lg_channels` | `0x8048` | LG Channels | |
| `alexa` | `0x800C` | Alexa | |

Power is infrared only and has no code. Long presses never produce a separate code: gestures such
as hold and repeat are timed by gyromote from the down/up edges.

In `0xFD` only one code is present at a time, so two buttons pressed together are seen as one.
