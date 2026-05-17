# Linux editions plan: desktop and server/CLI

`voice-keyboard` should treat Linux as two different runtime targets instead of one generic platform.

## 1. Linux desktop edition

Target environment:

- GNOME, KDE, XFCE, Wayland, or X11 desktop sessions
- User has a graphical session
- Keyboard focus exists in normal applications

Expected behavior:

- Tray application or background daemon
- Global hotkey to start/stop recording
- Speech-to-text result is inserted into the focused application
- Optional clipboard fallback
- Device selection UI or config file

Typical implementation details:

- GUI/tray entry point
- Desktop hotkey integration
- Text injection through desktop-specific backends
- Wayland/X11 compatibility handling

This edition is closest to the original desktop voice input product.

## 2. Linux server/CLI edition

Target environment:

- Headless Linux servers
- Single-board computers such as WalnutPi or Raspberry Pi
- SSH-only systems
- No X11, Wayland, tray, or desktop hotkey support

Expected behavior:

- Run completely from the command line
- Record once or loop continuously
- Print transcribed text to stdout
- Optionally write text to a file, clipboard backend, HTTP endpoint, or local IPC socket
- Suitable for shell workflows, automation, and terminal-based input

Useful commands:

```bash
vk-cli --list-devices
vk-cli --once
vk-cli --once --seconds 5
vk-cli --loop
```

Design principle:

> The CLI edition should not import or require GUI-only modules at startup.

This matters because libraries such as `pynput` may fail immediately on headless systems with errors like `Bad display name ""`.

## Why the split is necessary

A desktop Linux app and a headless Linux server app have different assumptions.

Desktop Linux can assume:

- A graphical session exists.
- A focused input field exists.
- Hotkeys and text injection are meaningful.

Server Linux cannot assume any of those. On a pure CLI system, the useful output is usually stdout, a file, an API, or an integration with another terminal program.

Trying to force one Linux entry point to support both tends to make the app fragile. A clean split makes both editions simpler.

## Current WalnutPi findings

A WalnutPi headless deployment was tested with AirPods Pro 3.

What worked:

- SSH operation
- CLI entry point
- OpenAI-compatible STT/LLM configuration through a custom base URL
- AirPods Bluetooth pairing
- AirPods A2DP playback

What did not work:

- AirPods microphone capture through the onboard WalnutPi Bluetooth controller

The Bluetooth microphone failure is documented separately in:

- `docs/walnutpi-airpods-bluetooth-mic.md`

The practical recommendation for the server/CLI edition is to use a USB microphone or a Linux-compatible USB Bluetooth adapter with working SCO/HFP-over-HCI support.

## Suggested package layout

Long term, the project can expose separate entry points:

```text
voice-keyboard-desktop
voice-keyboard-cli
voice-keyboard-server
```

Possible meanings:

- `voice-keyboard-desktop`: tray/hotkey/focused-app insertion
- `voice-keyboard-cli`: record and print result in the terminal
- `voice-keyboard-server`: long-running local service with HTTP/WebSocket/IPC API

The CLI and server editions can share the same core modules:

- audio capture
- speech-to-text
- LLM cleanup/editor
- config loading
- device listing

The desktop edition can build on the same core modules but keep GUI, hotkey, and text injection code isolated from headless imports.
