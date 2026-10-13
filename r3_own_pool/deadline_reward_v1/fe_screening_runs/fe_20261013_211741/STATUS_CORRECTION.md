# STATUS CORRECTION — original run is INCOMPLETE

The FE_RESULTS.json inside this directory says "COMPLETE" — that is
WRONG. The run contained 10 ERROR entries (DeepSeek/Qwen all failed
with ModuleNotFoundError before dispatch). The program incorrectly
continued after errors instead of stopping (fail-stop violation).

This run must be treated as INCOMPLETE / INVALID_FOR_FULL_PAIRED_SCREENING.

Original files preserved unmodified. This correction note is the only
addition. The 10 GLM responses are valid as raw data for analysis.
