# Voice Keyboard Engine — Agent Guide

## Repository Intent

This repository contains Voice Keyboard Engine, the local voice-driven keyboard efficiency layer that turns speech into text changes or keyboard-style operations in the current input environment.

Use the project language in [CONTEXT.md](CONTEXT.md). The boundary decision is recorded in [docs/adr/0001-voice-keyboard-engine-boundary.md](docs/adr/0001-voice-keyboard-engine-boundary.md).

Do not move account UI, subscriptions, payments, entitlement policy, provider billing, or TypeUp product flows into this repository.

## Domain Language

Prefer these domain terms in documentation and code-level explanations:

- **Voice Keyboard Engine**, not TypeUp Engine or Agent when describing the domain.
- **Voice Keyboard Operation**, not AI command or prompt when describing a user-requested keyboard-style action.
- **Dictation Mode**, not normal mode or PTT mode when describing the user intent.
- **Instruction Mode**, not AI mode when describing intent-driven operations.
- **Capture Path**, not hardware mode or software mode when describing where speech enters the engine.
- **Tracked Segment** and **Explicit Selection**, not TextBuffer or selected text when describing the domain rule.
- **Speech Interpretation Provider**, not a concrete vendor name when discussing the domain boundary.

Implementation terms such as `agent`, `TextBuffer`, STT provider names, LLM provider names, and hotkey names are fine inside implementation notes.

## Runtime Entry Points

| Entry point | Purpose |
| --- | --- |
| `python -m agent.main` | Desktop/local engine runtime |
| `python -m agent.main --no-serial` | Software Capture Path without hardware serial receiver |
| `python -m agent.cli` | Headless command-line dictation |
| `python -m agent.windows_tray` | Windows tray wrapper |

Useful commands:

```bash
.venv/bin/python -m agent.main --list-devices
.venv/bin/python -m agent.main --no-serial
.venv/bin/python -m agent.cli --once --seconds 5
pytest
```

On macOS, Python.org builds may need:

```bash
SSL_CERT_FILE=$(.venv/bin/python -c "import certifi; print(certifi.where())") \
  .venv/bin/python -m agent.main --no-serial
```

## Core Modules

| File | Responsibility |
| --- | --- |
| `agent/main.py` | Desktop runtime composition, config loading, monitors, serial reader, audio runtime |
| `agent/cli.py` | Headless record-and-print dictation |
| `agent/push_to_talk.py` | PTT hotkey capture and utterance dispatch |
| `agent/audio_monitor.py` | VAD capture path |
| `agent/stt.py` | Speech-to-text provider adapters |
| `agent/llm_editor.py` | LLM provider adapters for text operations |
| `agent/ai_intent.py` | Instruction Mode classification and deterministic fallbacks |
| `agent/ai_handler.py` | Instruction Mode orchestration and input side effects |
| `agent/typer.py` | Cross-platform text insertion, selection replacement, erase, shortcuts |
| `agent/text_buffer.py` | Implementation support for Tracked Segment behavior |
| `agent/keyboard_monitor.py` | Backspace/Delete/Enter monitoring for tracked text sync |
| `agent/mouse_monitor.py` | Cursor movement detection for tracked text safety |
| `agent/memo_store.py` | Reusable Text Memory persistence |
| `agent/config.py` | `config.yaml` and `.env` loading |

## Configuration Shape

Main configuration lives in `config.yaml`.

Important sections:

- `stt`: provider used for Dictation Mode speech recognition.
- `llm`: provider used for Instruction Mode text interpretation and generation.
- `ai_stt`: optional separate speech recognition provider for Instruction Mode.
- `audio`: capture mode, hotkeys, device selection, and VAD settings.
- `typing`: text insertion backend.

Use `typing.method: clip` for applications that reject Unicode keyboard event injection.

## Platform Notes

| Concern | macOS | Windows | Linux |
| --- | --- | --- | --- |
| Unicode insertion | Quartz `CGEventKeyboardSetUnicodeString` | `SendInput + KEYEVENTF_UNICODE` | X11/XTest path |
| Clipboard fallback | Available | Recommended for some Electron apps | Available where clipboard tooling works |
| Permissions | Accessibility, input monitoring, microphone | UAC and input APIs | X11/input permissions |
| Headless use | Use `agent.cli` | Use `agent.cli` | Use `agent.cli` |

Keep desktop-specific imports out of `agent.cli`; headless Linux cannot assume X11, Wayland, tray, global hotkeys, or a focused input field.

## Development Rules

- Keep `CONTEXT.md` as a glossary only. Do not add implementation decisions or provider setup instructions there.
- Add ADRs under `docs/adr/` only for hard-to-reverse decisions that need context.
- Prefer generic engine behavior in this repository. Keep TypeUp-specific integration behind provider or adapter boundaries.
- Do not reintroduce old docs as long-form design dumps. If material is operational, put it in README or packaging docs. If it is a decision, use an ADR. If it is domain language, update `CONTEXT.md`.
- Do not treat chat-style responses as a core Voice Text Operation unless they change the Input Environment.

## Agent skills

### Issue tracker

Issues and PRDs live in GitHub Issues for `wangqioo/voice-keyboard`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default five-label triage vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo with root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.

## Verification

Run focused tests when editing a module:

```bash
pytest test/test_ai_intent.py
pytest test/test_ai_handler.py
pytest test/test_typing.py
```

Run the full suite before broader changes:

```bash
pytest
```

Typing and global hotkey behavior often require OS permissions and may not be fully covered by automated tests.
