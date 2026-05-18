# Voice Keyboard Engine

Voice Keyboard Engine is a local voice-driven keyboard efficiency engine. It turns speech into text changes and keyboard-style operations in the current input environment, so common typing, editing, shortcut, and recall workflows can be driven by voice instead of repeated manual keyboard actions.

For the domain language, read [CONTEXT.md](CONTEXT.md). For the repository boundary decision, read [docs/adr/0001-voice-keyboard-engine-boundary.md](docs/adr/0001-voice-keyboard-engine-boundary.md).

This repository owns the standalone local engine. TypeUp desktop packaging and TypeUp backend account, subscription, payment, quota, and cloud entitlement behavior live outside this repository.

## Capabilities

- **Dictation Mode**: hold a hotkey, speak, and insert the spoken text into the focused input field.
- **Instruction Mode**: hold a separate hotkey, speak an instruction, and let the engine revise, generate, remove, reverse, recall reusable text, or invoke shortcuts. The product model is voice-driven keyboard operation, not chat-first or AI-native interaction. App-aware shortcut invocation is experimental.
- **Software Capture Path**: use a computer microphone, USB microphone, Bluetooth microphone, or other audio input already available to the OS.
- **Hardware Capture Path**: use a dedicated Voice Keyboard device as the capture source when hardware is connected.
- Cross-platform text insertion through Unicode event injection or clipboard paste fallback.
- Multiple Speech Interpretation Providers through configuration.

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/wangqioo/voice-keyboard.git
cd voice-keyboard
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.yaml.example config.yaml
```

On Windows:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy config.yaml.example config.yaml
```

Edit `config.yaml` and configure at least `stt`. Configure `llm` to enable Instruction Mode operations that need language model interpretation.

## Run

List available microphones:

```bash
.venv/bin/python -m agent.main --list-devices
```

Run with the Software Capture Path:

```bash
.venv/bin/python -m agent.main --no-serial
```

Run with a serial hardware receiver:

```bash
.venv/bin/python -m agent.main
```

On macOS, Python.org builds may need an explicit certificate path for provider HTTPS/WebSocket calls:

```bash
SSL_CERT_FILE=$(.venv/bin/python -c "import certifi; print(certifi.where())") \
  .venv/bin/python -m agent.main --no-serial
```

## Headless CLI

For server or SSH-only environments, use the headless CLI. It records audio and prints recognized text instead of inserting into a focused input field.

```bash
.venv/bin/python -m agent.cli --list-devices
.venv/bin/python -m agent.cli --once
.venv/bin/python -m agent.cli --once --seconds 5
.venv/bin/python -m agent.cli --loop
```

The CLI path should stay separate from desktop-only imports and assumptions.

## Configuration

Primary configuration lives in `config.yaml`. `.env` is also supported for deployment scenarios.

Important sections:

- `stt`: Speech Interpretation Provider adapter used for Dictation Mode speech recognition.
- `llm`: Speech Interpretation Provider adapter used for Instruction Mode text interpretation and generation.
- `ai_stt`: optional separate Speech Interpretation Provider adapter for Instruction Mode speech recognition.
- `audio`: capture mode, hotkeys, microphone selection, and VAD settings.
- `typing`: text insertion backend, usually `unicode` or `clip`.

Common audio settings:

```yaml
audio:
  mode: ptt
  ptt_key: shift_r
  ai_key: alt_r
  device: auto
```

Use `typing.method: clip` for applications that reject Unicode keyboard event injection, such as some Electron apps.

## Runtime Entry Points

- `python -m agent.main`: desktop/local engine runtime.
- `python -m agent.cli`: headless dictation CLI.
- `python -m agent.windows_tray`: Windows tray wrapper.

Useful desktop runtime flags:

- `--no-serial`: do not search for a hardware serial receiver.
- `--port <path>`: use a specific serial port.
- `--list-devices`: print available input devices and exit.
- `--install` / `--uninstall`: register or remove autostart.
- `--headless`: run without the floating status window.
- `--no-ui`: run without menu bar or main window.

## Tests

Run the test suite:

```bash
pytest
```

Run a typing smoke test after granting required OS permissions:

```bash
.venv/bin/python test/test_typing.py
```

Simulate a serial device on platforms that support pseudo terminals:

```bash
.venv/bin/python test/simulate_device.py
.venv/bin/python -m agent.main --port <printed-port>
```

## Packaging

Platform packaging lives under `packaging/`:

- `packaging/macos/`
- `packaging/windows/`
- `packaging/linux/`

Packaging code should wrap the local engine. Product-specific account, subscription, and entitlement flows should remain outside this repository.

## License

MIT
