# Voice Keyboard

Voice Keyboard is a local-first voice keyboard engine for turning speech into text input and keyboard-style operations on the current computer.

It is not a chatbot. The goal is to make common input work faster: dictation, rewriting selected text, triggering shortcuts, switching windows, launching apps, and recalling short reusable text snippets.

The project currently focuses on the Windows desktop workflow while keeping macOS and Linux/headless code paths available where supported. Dictation correction learning is currently strongest on macOS because it uses Accessibility, input-monitoring, IME commit events, and an OCR fallback when focused text cannot be read directly.

## What It Does

- Dictation mode: hold a hotkey, speak, and insert recognized text into the active input field.
- Instruction mode: hold a separate hotkey and speak an operation such as rewrite, summarize, delete, continue, press a shortcut, open an app, or recall a memo.
- Local UI: Windows tray menu, main window, language switching, hotkey settings, history, memo management, and AI intent diagnostics.
- Memo store: save and recall explicit short text snippets such as addresses, emails, and reusable phrases.
- Dictation correction memory: learn repeated manual corrections as a local wrong-to-correct dictionary and apply them to later dictation.
- Intent feedback loop: collect local intent samples, correct mistakes, sync with a training server, and use local overrides/model data to improve future intent decisions.
- Headless CLI: record and print recognized speech without touching the active input field.

## Current Status

The Windows client has the main local workflow in place:

- Tray and main-window entry points
- Dictation and instruction hotkeys
- Raw dictation and light-polish modes
- Shortcut, app-launch, window, memo, and text-edit operations
- AI intent diagnostics and correction workflow
- Local-only correction mode when no training server is configured
- Optional training server for sample upload, review, correction, and stats

The intent model loop is still evolving. The current implementation combines deterministic rules, local correction overrides, lightweight local intent data, and optional LLM interpretation. A stronger semantic classifier can be trained later from corrected real usage samples.

## Requirements

- Python 3.11 or newer
- A microphone
- API access for at least one speech interpretation provider
- Windows 10/11 for the full tray and desktop UI experience

Platform notes:

- Windows is the best-supported desktop target.
- macOS requires microphone, Accessibility, and input-monitoring permissions. Dictation correction learning also benefits from Screen Recording permission when the OCR fallback is enabled.
- Linux/headless usage is mainly via `agent.cli`; desktop insertion depends on the local input stack.

## Quick Start

### Windows

```powershell
git clone https://github.com/wangqioo/voice-keyboard.git
cd voice-keyboard
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy config.yaml.example config.yaml
copy .env.example .env
```

Edit `config.yaml` or `.env`, then start the client:

```powershell
.\.venv\Scripts\python -m agent.main --no-serial
```

Useful Windows commands:

```powershell
.\.venv\Scripts\python -m agent.main --list-devices
.\.venv\Scripts\python -u -m agent.main --no-serial --no-ui
.\.venv\Scripts\python -m agent.windows_tray
```

### macOS / Linux

```bash
git clone https://github.com/wangqioo/voice-keyboard.git
cd voice-keyboard
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.yaml.example config.yaml
cp .env.example .env
```

Start the runtime:

```bash
scripts/run-local.sh
```

Run in the background and write PID/log paths:

```bash
scripts/run-local.sh --background
scripts/run-local.sh --status
```

On macOS, `--status` also reports the `com.voicekeyboard.agent` LaunchAgent when that install path is active, even if the script PID file is missing or stale.

Stop the local runtime:

```bash
scripts/run-local.sh --kill-only
```

`--kill-only` stops local `agent.main` processes started from this checkout. If the macOS LaunchAgent is installed, unload or restart it with `launchctl` instead.

List audio devices:

```bash
.venv/bin/python -m agent.main --list-devices
```

On macOS, System Settings grants apply to the launching app. Source runs usually need permissions for Terminal/iTerm/Python; packaged runs need permissions for `Voice Keyboard.app`. Check the current launch identity with:

```bash
scripts/run-local.sh --permissions
```

## Configuration

The main configuration file is:

```text
config.yaml
```

You can also place user-specific configuration at:

```text
~/.voice-keyboard/config.yaml
```

If the user-level file exists, it takes priority over the repository-local `config.yaml`.

Common sections:

- `stt`: speech-to-text provider for dictation.
- `ai_stt`: optional separate speech-to-text provider for instruction mode.
- `polish_stt`: optional speech-to-text provider settings for polished dictation.
- `llm`: model provider for instruction interpretation, rewriting, polishing, and generated text.
- `audio`: capture mode, hotkeys, audio device, and VAD settings.
- `correction_memory`: local Dictation Mode correction dictionary and learning behavior.
- `typing`: text insertion and shortcut execution behavior.
- `instruction_mode`: local intent rules, memo triggers, overrides, diagnostics, and training sync.

Typical hotkey shape:

```yaml
audio:
  mode: ptt
  ptt_key: shift_r
  ai_key: alt_r
  device: auto
```

Typical correction-memory shape:

```yaml
correction_memory:
  enabled: true
  path: ~/.voice-keyboard/correction_memory.json
  confirm_threshold: 2
  observe_window_seconds: 30
  max_pending: 5
  screen_ocr_fallback: true
  screen_ocr_after_edit_seconds: 0.8
  debug: false
```

After Dictation Mode inserts text, repeated manual fixes such as `王之行 -> 王知行`
can be learned locally and applied before future dictation text reaches the
current input field. The macOS UI includes a `词典` tab for confirmed and
candidate entries.

Correction entries are intentionally narrow: automatic learning only accepts
Chinese wrong-to-correct fragments from 2 to 5 characters. Longer sentence-like
replacements and ordinary English word corrections are ignored to reduce
accidental global replacements.

How the correction-memory loop works:

1. Dictation Mode recognizes speech and applies existing Correction Dictionary entries before insertion.
2. The engine remembers recently inserted Dictation text for a short observation window.
3. If the user manually fixes the inserted text, the engine observes the focused text, IME committed text, key edits, or macOS OCR fallback.
4. Repeated evidence creates a Correction Candidate and then promotes it to the confirmed Correction Dictionary after `confirm_threshold`.
5. The `词典` tab can review confirmed entries, review candidates, delete entries, or copy the storage path.

Correction Memory is separate from Memo. Memo stores user-provided snippets for later recall; Correction Memory only stores local wrong-to-correct pairs for Dictation.

Secrets should stay out of git. Use `config.yaml`, `.env`, environment variables, or a local secret manager. The repository tracks only examples such as `config.yaml.example` and `.env.example`.

## Runtime Entry Points

| Command | Purpose |
| --- | --- |
| `python -m agent.main` | Desktop/local engine runtime |
| `python -m agent.main --no-serial` | Desktop runtime without hardware serial receiver |
| `python -m agent.main --list-devices` | Print available audio devices |
| `python -m agent.main --no-serial --no-ui` | Runtime without the main window, useful for debugging |
| `python -m agent.windows_tray` | Windows tray wrapper |
| `python -m agent.cli` | Headless command-line dictation |

## Headless CLI

The CLI records audio and prints recognition results. It does not type into the current input field.

Windows:

```powershell
.\.venv\Scripts\python -m agent.cli --list-devices
.\.venv\Scripts\python -m agent.cli --once
.\.venv\Scripts\python -m agent.cli --once --seconds 5
.\.venv\Scripts\python -m agent.cli --loop
```

macOS / Linux:

```bash
.venv/bin/python -m agent.cli --list-devices
.venv/bin/python -m agent.cli --once
.venv/bin/python -m agent.cli --once --seconds 5
.venv/bin/python -m agent.cli --loop
```

## Intent Training Server

The optional training server receives local intent samples, exposes review APIs, and includes a small web review console at `/review`.

Install server dependencies:

```powershell
pip install -r requirements-server.txt
```

Start the server:

```powershell
$env:INTENT_TRAINING_DATABASE_URL = "sqlite:///./intent_training.db"
$env:INTENT_TRAINING_UPLOAD_TOKEN = "change-me"
uvicorn training_server.api:app --host 0.0.0.0 --port 8000
```

Upload local samples:

```powershell
python tools/upload_intent_samples.py --server http://SERVER:8000 --token change-me
```

Dry run without uploading:

```powershell
python tools/upload_intent_samples.py --dry-run
```

More details:

- [Intent training overview](docs/intent-training.md)
- [Intent training server](docs/intent-training-server.md)
- [Stage development plan](docs/stage-development-plan.md)

## Development

Run the full non-interactive test suite:

```powershell
python -m unittest discover -s test
python -m compileall -q agent training_server tools test
```

macOS / Linux:

```bash
scripts/test-local.sh
python -m compileall -q agent training_server tools test
```

`test/test_typing.py` is a manual smoke script for real OS text insertion. It is safe to import during automated discovery, but it only types into the active field when run directly:

```bash
python test/test_typing.py
```

Some behavior depends on OS permissions, a real focused input field, or an available desktop session. For day-to-day development, prefer focused unit tests around the module you changed.

## Packaging

Packaging resources live under:

- `packaging/windows/`
- `packaging/macos/`
- `packaging/linux/`

On managed corporate computers, unsigned executables may be blocked. For real distribution, use a trusted release or code-signing process.

## Project Docs

- [Agent guide](AGENTS.md)
- [Ubiquitous language](UBIQUITOUS_LANGUAGE.md)
- [Input Environment architecture](docs/architecture/input-environment-seam.md)
- [Dictation correction memory architecture](docs/architecture/dictation-correction-memory.md)
- [Current stage plan](docs/stage-development-plan.md)
- [Intent training](docs/intent-training.md)
- [Intent training server](docs/intent-training-server.md)

## Roadmap

Near-term work:

1. Continue improving the Windows AI intent correction workflow.
2. Accumulate corrected real-world intent samples.
3. Export higher-quality training datasets.
4. Train and evaluate a stronger local intent model.
5. Connect the improved model back into the Windows runtime.
6. Keep polishing tray, main-window, hotkey, history, and memo configuration flows.

## License

MIT
