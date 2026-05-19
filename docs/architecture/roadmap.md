# Architecture Roadmap

This roadmap uses the domain language from `CONTEXT.md` and the architecture language from `AGENTS.md`.

## 1. Input Environment Seam

Status: in progress, accepted by ADR-0002 and ADR-0005.

Deepen the module that owns Explicit Selection, insertion, replacement, deletion, and current-input-window behavior. This is the first priority because Instruction Mode depends on these rules for Text Revision, Text Removal, Text Generation, Reusable Text Operation, and Shortcut Invocation.

Initial implementation:

- `agent/input_environment.py`
- `agent/text_io.py`
- `AIHandler` now uses the Input Environment seam for text-side effects.
- Input Environment now owns Text Revision / Text Removal target lookup and text-side effects.
- Input Environment now owns generated-text insertion around Explicit Selection for Text Generation and Reusable Text Operation output.
- Platform text IO calls now sit behind a small adapter used by the Input Environment implementation.
- Text Revision and specific Text Removal now require Explicit Selection unless the user clearly asks for the whole current Operation Window.
- Generic delete can remove the current Operation Window, or fall back to Select All + Delete when no window is available.
- Next targeting work should broaden platform support for focused-field Operation Windows while preserving the rule that no-selection local partial edits fail closed.

## 2. Instruction Mode Execution

Status: in progress, bounded by ADR-0007.

After Input Environment is behind a seam, deepen Instruction Mode around Voice Text Operation execution.

Target direction:

- Convert classifier output into explicit operation objects or structured operation results.
- Keep prompt construction and deterministic fallbacks in `ai_intent`.
- Move text-side effects into the Input Environment interface.
- Keep Reusable Text Memory behind a small interface.
- Treat spoken undo as a Shortcut Invocation of the current application undo action.

Initial implementation:

- `agent/voice_text_operation.py`
- `agent/instruction_executor.py`
- `agent/reusable_text_memory.py`
- `AIHandler` now leaves undo to the executor as a Shortcut Invocation.
- `AIHandler` now dispatches typed Voice Text Operation values instead of raw classifier dictionaries.
- Instruction Mode execution now lives behind an executor seam, leaving `AIHandler` focused on runtime orchestration.
- Reusable Text Operation rules and Reusable Text Memory key matching now live behind a Reusable Text Memory module; the executor only applies insert/show results to the Input Environment.
- Text Revision and Text Removal use structured Replacement Plans for selected text and whole-scope requests instead of full-context rewrites.
- Atomic Operation Stack support should be a later slice after stack data structures, local risk policy, and executor sequencing exist. Until then, the classifier should ask users to split explicit multi-step instructions.

## 3. Application Shortcut Catalog

Status: in progress, accepted by ADR-0008.

Deepen Shortcut Invocation around local application-aware catalogs so Voice Keyboard Engine can act as a lightweight voice-to-keyboard layer in Office, WPS, Feishu, and other current Input Environments.

Initial implementation:

- `agent/app_shortcut_presets.py`
- Universal editing actions such as undo, redo, bold, italic, underline, and find now live in the Global Shortcut Catalog instead of being repeated per application.
- macOS built-in application shortcut presets are intentionally empty until there is a validated surface-aware adapter for Office, WPS, and Feishu/Lark. Local `typing.application_shortcuts` remains the customization path.
- macOS application launch actions are discovered from installed `.app` bundles, with built-in aliases for common spoken names such as Feishu/Lark, Word, Excel, PowerPoint/PPT, WPS, and Google Chrome.
- macOS system window actions are exposed as built-in System Actions and execute through Accessibility frame updates rather than physical key chords.
- The macOS menu bar UI now includes a `快捷键` tab for catalog visibility, disabling/restoring named actions, and adding custom global shortcut actions.
- `agent.local_operation_catalog` now owns catalog entry metadata, de-duplication, blocking, and high-risk policy decisions.
- `agent.app_launcher` now owns application-launch discovery, aliases, config parsing, and launch execution.
- `agent.macos_window_actions` now owns macOS Accessibility window frame actions.
- `agent.typer` still owns key parsing and key emission while delegating catalog policy, app launch, and window actions to deeper modules.
- Instruction Mode already receives the current active application and local Shortcut Catalog names, so a Speech Interpretation Provider can choose a named Shortcut Invocation without inventing key sequences.
- Next work should add a validated surface-aware adapter for application-specific Office, WPS, and Feishu/Lark shortcuts, then add Windows app identities and presets for the same narrow slice.

## 4. Capture Path

Status: in progress.

Unify PTT, VAD, hardware serial, and headless CLI around utterance events without importing desktop-only modules into headless paths.

Target direction:

- Keep `agent.cli` headless.
- Keep `PushToTalk` and `AudioMonitor` as adapters.
- Concentrate audio frame and VAD lifecycle rules where they can be tested without OS hooks.

Initial implementation:

- `agent/capture_path.py`
- `agent/capture_path_runtime.py`
- `PushToTalk` now dispatches typed `UtteranceEvent` values internally while keeping the existing callback adapter interface.
- `PushToTalk` now delegates enabled/disabled state, active capture pairing, and Dictation Mode polish toggling to a Capture Path runtime state machine.

## 5. Speech Interpretation Provider Adapters

Status: in progress.

Normalize Speech Interpretation Provider adapter shape after the core operation flow is clearer.

Target direction:

- Keep concrete provider names out of the domain model.
- Reduce duplication between TypeUp backend Speech Interpretation Provider adapter credential refresh paths.
- Consider a registry for text interpretation adapters similar to speech recognition adapters only if it reduces real caller complexity.

Initial implementation:

- `agent/typeup_backend_auth.py`
- `agent/speech_interpretation_providers.py`
- TypeUp backend Speech Interpretation Provider adapters now share credential reload, refresh, auth header, and error-message handling.
- Runtime composition now constructs Dictation Mode, micro-polish, Instruction Mode speech recognition, and text-operation providers through one factory.

## 6. Runtime Composition

Status: in progress.

Once the core seams exist, separate process entry points from engine composition.

Target direction:

- `agent.main` should parse process flags and delegate composition.
- Windows tray, desktop host adapters, desktop runtime, and tests should reuse the same composition module where practical.

Initial implementation:

- `agent/runtime_composition.py`
- `agent/dictation_mode.py`
- Desktop `agent.main` and `agent.windows_tray` now use the Runtime Composition module for backend lifecycle construction.
- Dictation Mode interpretation, cleanup, status, history, and insertion now live behind a dedicated module while `agent.main` preserves the older callback factory.
