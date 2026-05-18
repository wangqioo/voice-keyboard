# Instruction Mode operation effects

Instruction Mode should record reversible text changes as explicit operation effects instead of ad hoc tuples in `AIHandler`. An operation effect describes the forward change and how Operation Reversal should compensate for it, while `AIHandler` remains responsible for orchestration. This gives Text Revision, Text Removal, Text Generation, and later Reusable Text Operation insertions a shared reversal model without coupling the model to prompt classification or platform typing details.
