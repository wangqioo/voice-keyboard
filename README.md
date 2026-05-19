# Voice Keyboard Engine

Voice Keyboard Engine is a local voice-driven keyboard efficiency engine. It turns speech into text changes and keyboard-style operations in the current input environment, so typing, editing, shortcut, window, application, and memo workflows can be driven by voice.

For the domain language, read [CONTEXT.md](CONTEXT.md). For the repository boundary decision, read [docs/adr/0001-voice-keyboard-engine-boundary.md](docs/adr/0001-voice-keyboard-engine-boundary.md).

This repository owns the standalone local engine. TypeUp desktop packaging and TypeUp backend account, subscription, payment, quota, and cloud entitlement behavior live outside this repository.

## Capabilities

- **Dictation Mode**: hold the dictation hotkey, speak, and insert the recognized text into the current input environment. Dictation is applied as direct typing; it does not use a general copy/paste fallback.
- **Instruction Mode**: hold the instruction hotkey and speak a keyboard-style operation. The engine can revise text, generate text, remove text, invoke shortcuts, launch local applications, operate the current window, and save or recall memos.
- **Text Revision**: explicit selection takes precedence. Without an explicit selection, revision defaults to the latest tracked segment inserted by the engine. Whole-scope wording such as "delete all" or "rewrite the whole input" targets the current safe input scope.
- **Text Generation**: generated text is meant to enter the current input environment. The engine waits for the complete model output, then inserts it as one tracked segment so the next revision can edit it directly.
- **Text Removal**: selected text can be removed directly. Broad removal requires explicit whole-scope wording; partial removal without a safe target fails closed and asks for selection.
- **Memo Operation**: save, recall, delete, and list short user-provided memos. Memo is only a reusable text snippet feature, not chat memory, user profiling, or a personal knowledge base.
- **Shortcut Invocation**: trigger curated low-conflict keyboard-style actions from local shortcut catalogs.
- **Application Launch**: open locally discovered or configured applications by voice.
- **System Window Action**: move, resize, maximize, minimize, or fullscreen the current desktop window through local system capabilities.
- **Software Capture Path**: record through a computer microphone, USB microphone, Bluetooth microphone, or other OS-visible audio input.
- **Hardware Capture Path**: record through a dedicated Voice Keyboard device when hardware is connected.

The product model is voice-driven keyboard operation, not chat-first interaction. AI is an implementation detail used by some Instruction Mode operations.

## Platform Status

**Current verification baseline: macOS.** The feature work in this version was developed and tested on macOS. The local automated test suite was run on macOS, and the real input-field behavior was debugged against macOS desktop permissions, keyboard injection, and Accessibility APIs.

**Windows is not fully validated yet.** The repository contains basic Windows adapters for direct typing, tray startup, global shortcuts, and simple foreground-window actions, but this version has not been tested end to end on Windows. Porting this behavior to Windows must include a full Windows test pass from startup through real text insertion, selection replacement, no-selection revision, whole-scope deletion, memo recall, shortcut invocation, and window actions.

The macOS build currently supports:

- Dictation into the current input environment by direct typing.
- Immediate recording status feedback when the dictation hotkey is pressed.
- Instruction Mode text generation, with complete model output inserted as one tracked segment.
- No-selection Text Revision of the latest tracked segment inserted by the engine.
- Explicit-selection Text Revision and Text Removal through macOS Accessibility when available.
- Whole-scope rewrite and whole-scope deletion when the spoken instruction explicitly asks for the whole input.
- Memo save, recall, delete, and list operations.
- Shortcut Invocation from curated global and application-aware shortcut catalogs.
- Application Launch for locally discovered or configured applications.
- macOS System Window Actions including left half, right half, maximize, center, and fullscreen handling.
- Software Capture Path through OS-visible microphones.
- Hardware Capture Path through a serial Voice Keyboard device when connected.

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

Edit `config.yaml` and configure at least `stt`. Configure `llm` to enable Instruction Mode operations that need language model interpretation or generation.

Packaged or live desktop runs may use `~/.voice-keyboard/config.yaml`; when that file exists, it takes precedence over the repository `config.yaml`.

## Run

List available microphones:

```bash
.venv/bin/python -m agent.main --list-devices
```

Run the local engine with the Software Capture Path:

```bash
.venv/bin/python -m agent.main --no-serial
```

Run without the main UI, useful for terminal testing:

```bash
.venv/bin/python -u -m agent.main --no-serial --no-ui
```

Run with a serial hardware receiver:

```bash
.venv/bin/python -m agent.main
```

On macOS, grant the runtime the required OS permissions:

- Microphone, for audio capture.
- Accessibility, for keyboard input and window operations.
- Input Monitoring, when the selected typing backend or hotkey listener requires it.

Python.org builds may also need an explicit certificate path for provider HTTPS/WebSocket calls:

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

Primary development configuration lives in `config.yaml`. User-level runtime configuration lives in `~/.voice-keyboard/config.yaml`. `.env` is also supported for deployment scenarios.

Important sections:

- `stt`: Speech Interpretation Provider adapter used for Dictation Mode speech recognition.
- `ai_stt`: optional separate Speech Interpretation Provider adapter for Instruction Mode speech recognition.
- `polish_stt`: optional recognition configuration for polish-style speech flows.
- `llm`: Speech Interpretation Provider adapter used for Instruction Mode interpretation, revision, and generation.
- `audio`: capture mode, hotkeys, microphone selection, and VAD settings.
- `typing`: text insertion backend configuration.

Common audio settings:

```yaml
audio:
  mode: ptt
  ptt_key: shift_r
  ai_key: alt_r
  device: auto
```

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

Run the local non-interactive test suite:

```bash
scripts/test-local.sh
```

Run a focused typing smoke test only after granting required OS permissions and preparing a real target input field:

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
