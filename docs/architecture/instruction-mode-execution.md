# Instruction Mode Execution

This design expands ADR-0003 into an implementation plan for deepening Instruction Mode.

## Current Friction

`AIHandler` is now narrower, but still owns runtime orchestration responsibilities:

- transcribing Instruction Mode speech
- gathering Explicit Selection and Tracked Segment context
- calling intent classification
- recording history and status/error states
- coordinating temporary feedback cleanup

`InstructionModeExecutor` owns Voice Text Operation execution. The remaining friction is deciding which feedback and orchestration policy belongs with runtime handling and which belongs with Voice Text Operation execution.

## Target Modules

Instruction Mode execution now lives across a small module set:

```text
agent/voice_text_operation.py
agent/instruction_executor.py
agent/operation_history.py
agent/reusable_text_memory.py
```

`agent/operation_history.py` models reversible text effects:

- replacing existing text with new text
- inserting new text
- deleting existing text

The history module should not call `typer`, `TextBuffer`, or providers. It describes what happened and keeps a bounded history. Execution now lives in `InstructionModeExecutor`; `AIHandler` remains the runtime orchestrator for transcription, context gathering, classification, status, and feedback cleanup.

Replacement-style operations should add one more boundary:

```text
Operation Window -> provider targeting -> Replacement Plan -> local verification -> text effect
```

The provider may use the full Operation Window to understand the instruction, but it should not return "the whole edited window" as the only result. It should return a structured plan that identifies the Operation Target and replacement text. `InstructionModeExecutor` should then ask the Input Environment to verify and apply that plan.

## Migration Slices

1. Done: add `OperationEffect` and `OperationHistory`.
2. Done: replace `_undo_stack` tuples in `AIHandler` with `OperationHistory`.
3. Done: keep a compatibility `_undo_stack` view during migration.
4. Done: move Operation Reversal logic to consume `OperationEffect`.
5. Done: convert classifier dictionaries into typed Voice Text Operation objects.
6. Done: move Voice Text Operation execution into `InstructionModeExecutor`.
7. Done: move Reusable Text Operation rules into `ReusableTextMemory`.
8. Done: model Replacement Plan data for Text Revision and Text Removal.
9. Done: change provider-facing prompts to request target text inside an Operation Window instead of a complete rewrite of the whole context.
10. Next: reduce `AIHandler` to runtime orchestration by moving any remaining Instruction Mode execution branching and feedback policy that belongs with Voice Text Operation handling into the executor.

## Test Surface

- History keeps at most the configured limit.
- Text Revision records old and new text.
- Text Generation records inserted text.
- Text Removal records deleted text.
- Operation Reversal consumes the latest effect first.
- Text Revision can replace a target span that is smaller than the Operation Window.
- Ambiguous or stale Replacement Plans fail without mutating text.
