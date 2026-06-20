# Dictation Correction Memory

Dictation Correction Memory is the local wrong-to-correct learning layer for Dictation Mode. It is separate from Memo: Memo saves user-provided snippets for later recall, while Correction Memory learns repeated fixes to dictated text and applies them before later Dictation text reaches the Input Environment.

## Runtime Flow

```text
Capture Path
  -> Dictation Mode transcribes speech
  -> existing Correction Dictionary entries are applied
  -> Input Environment inserts corrected text
  -> CorrectionLearningTracker remembers the inserted text
  -> CorrectionObservationHooks observe key, IME, and committed-text events
  -> manual edits are observed during the configured window
  -> repeated evidence promotes Correction Candidates to the Correction Dictionary
```

The main implementation files are:

- `agent/correction_memory.py`: persistence, inference, candidate promotion, tracking, and observation scheduling.
- `agent/correction_observation.py`: small runtime-facing hooks for key presses, key releases, committed text, and scheduler shutdown.
- `agent/dictation_mode.py`: applies the Correction Dictionary and remembers inserted Dictation text.
- `agent/performance_observer.py`: low-overhead stage timing for Dictation Mode.
- `agent/runtime_composition.py`: wires the observation hooks, PushToTalk capture events, and IME monitor.
- `agent/input_environment.py`, `agent/text_io.py`, and `agent/focused_text_capture.py`: expose focused-text and screen-text snapshots for correction learning.
- `agent/typer.py`: implements platform typing, focused text, and OCR primitives behind adapters.
- `agent/ime_commit_monitor.py`: observes committed IME text on macOS.
- `agent/macos_keyboard_listener.py`: uses Quartz key events on macOS for stable hotkey and edit tracking.
- `agent/screen_ocr_capture.py`: macOS OCR fallback when Accessibility text is unavailable or stale.
- `agent/ui/main_window.py`: `词典` tab for confirmed entries and candidates.

## Learning Rules

The engine only learns from recently inserted Dictation text. After insertion, `CorrectionLearningTracker` keeps a pending observation with the inserted text and a short shadow edit history from manual key events.

Observation sources are ordered by reliability:

1. Focused Accessibility text snapshot.
2. Text around the caret or the current Tracked Segment.
3. IME committed text observed from macOS event taps.
4. Shadow text reconstructed from key edits.
5. Screen OCR fallback, when enabled.

The inference step extracts wrong-to-correct pairs from the before/after text. Repeated evidence creates or updates Correction Candidates. Once evidence reaches `correction_memory.confirm_threshold`, the pair becomes a confirmed Correction Dictionary entry and is applied to later Dictation text.

Automatic learning is scoped to short Chinese correction fragments. A valid pair
must be 2 to 5 CJK characters on both sides. This covers names, ordinary words,
short terms, and most idioms while avoiding long sentence replacements. Ordinary
English word corrections are not learned automatically.

With the default `confirm_threshold: 2`, the same wrong-to-correct pair usually
needs two independent observations before it is promoted. If an entry is already
confirmed in the dictionary, it is applied immediately on the next matching
Dictation result.

## Configuration

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

The storage file contains confirmed entries and candidates. The UI reads the same path and can delete either kind of entry.

## Platform Notes

macOS has the full learning path today:

- Accessibility reads focused text and current text windows.
- Quartz key events feed manual edit tracking.
- IME committed text helps distinguish pinyin composition from committed Chinese text.
- Screen OCR can recover text from apps that do not expose reliable Accessibility text.

Windows and Linux can still apply an existing Correction Dictionary through Dictation Mode. Full automatic learning on those platforms needs equivalent focused-text, key-edit, and IME/commit adapters.

## Runtime Observability

Dictation Mode emits `[perf]` lines for the main latency stages:

- `dictation.observe_previous`
- `dictation.stt`
- `dictation.polish`
- `dictation.correction`
- `dictation.typing`
- `dictation.total`

Use these timings to distinguish provider latency from local typing/focus
latency. Correction-learning capture failures are still logged separately by
`agent/correction_memory.py` when debug or fallback paths are active.

## Test Surface

Important tests:

- `test/test_correction_memory.py`
- `test/test_dictation_mode.py`
- `test/test_runtime_composition.py`
- `test/test_capture_path.py`
- `test/test_ime_commit_monitor.py`
- `test/test_macos_keyboard_listener.py`
- `test/test_screen_ocr_capture.py`
- `test/test_ai_handler.py`
- `test/test_typer_shortcuts.py`

Run the full non-interactive suite with:

```bash
.venv/bin/python -m unittest discover -s test -v
```

`test/test_typing.py` is a manual OS insertion smoke script and only types when run directly.
