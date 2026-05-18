# Architecture Roadmap

This roadmap uses the domain language from `CONTEXT.md` and the architecture language from `AGENTS.md`.

## 1. Input Environment Seam

Status: in progress, accepted by ADR-0002 and ADR-0005.

Deepen the module that owns Explicit Selection, Tracked Segment safety, insertion, replacement, deletion, and cursor movement. This is the first priority because Instruction Mode depends on these rules for Text Revision, Text Removal, Text Generation, Reusable Text Operation, and Operation Reversal.

Initial implementation:

- `agent/input_environment.py`
- `agent/text_io.py`
- `AIHandler` now uses the Input Environment seam for text-side effects.
- Input Environment now owns Text Revision / Text Removal target lookup and Operation Reversal text effects.
- Input Environment now owns generated-text insertion around Explicit Selection for Text Generation and Reusable Text Operation output.
- Platform text IO calls now sit behind a small adapter used by the Input Environment implementation.
- Text Revision and Text Removal now prefer Explicit Selection, then the current safe text window exposed by the Input Environment, then safe Tracked Segment fallback.
- Next targeting work should broaden platform support for focused-field Operation Windows and keep separating that window from the smaller Operation Target that a provider proposes replacing.

## 2. Instruction Mode Execution

Status: in progress, accepted by ADR-0003 and bounded by ADR-0007.

After Input Environment is behind a seam, deepen Instruction Mode around Voice Text Operation execution.

Target direction:

- Convert classifier output into explicit operation objects or structured operation results.
- Keep prompt construction and deterministic fallbacks in `ai_intent`.
- Move text-side effects into the Input Environment interface.
- Keep Reusable Text Memory behind a small interface.
- Make Operation Reversal depend on recorded operation effects rather than ad hoc tuples.

Initial implementation:

- `agent/operation_history.py`
- `agent/voice_text_operation.py`
- `agent/instruction_executor.py`
- `agent/reusable_text_memory.py`
- `AIHandler` now records `OperationEffect` values and Operation Reversal consumes those effects.
- `AIHandler` now dispatches typed Voice Text Operation values instead of raw classifier dictionaries.
- Instruction Mode execution now lives behind an executor seam, leaving `AIHandler` focused on runtime orchestration.
- Reusable Text Operation rules and Reusable Text Memory key matching now live behind a Reusable Text Memory module; the executor only applies insert/show results to the Input Environment.
- Text Revision and Text Removal should move toward structured Replacement Plans instead of full-context rewrites.
- Atomic Operation Stack support should be a later slice after stack data structures, local risk policy, and executor sequencing exist. Until then, the classifier should ask users to split explicit multi-step instructions.

## 3. Capture Path

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

## 4. Speech Interpretation Provider Adapters

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

## 5. Runtime Composition

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
