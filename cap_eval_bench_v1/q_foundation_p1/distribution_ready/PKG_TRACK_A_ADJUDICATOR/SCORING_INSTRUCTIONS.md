# C9 Human Judge Calibration Instructions

Score every candidate independently using only the supplied question, context/table, and reference answer.

- 4: fully correct; key conclusion and reasoning are supported.
- 3: mostly correct; a minor omission does not change the main conclusion.
- 2: partly correct; contains a material omission or local error.
- 1: little correct content; main conclusion is wrong.
- 0: incorrect, irrelevant, unsupported, or no valid answer.

Rules:

1. Assign an integer score from 0 to 4 to every candidate label exactly once.
2. Do not rank candidates relative to each other; assess each independently.
3. Do not infer or record model identity.
4. Give a short evidence-based reason for every score.
5. Set reviewer_confidence to low, medium, or high.
6. Reviewers A and B must work independently before adjudication.
7. A score difference greater than one point requires adjudication; all other differences are retained for agreement statistics and resolved by the frozen adjudication rule before forming human gold.
