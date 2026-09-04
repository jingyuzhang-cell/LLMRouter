# ProgRouter-style E4 Reproduction

This directory is an independent, paper-guided baseline implementation. It does
not modify the frozen E4 collection protocol or raw logs.

The implementation order is intentionally staged:

1. `request_only`: task features, node type, candidate model.
2. `progress_lite`: request-only features plus frozen pre-action workflow state.
3. `progrouter_style`: explicit progress views, structured and semantic paths,
   and budget-aware meta-gating, only if `progress_lite` beats request-only.

All comparisons must use grouped task splits and the same estimator family and
hyperparameters for request-only and progress-lite. Semantic outcome labels are
not accessed until the 640-outcome frozen E4 collection is complete.

The upstream ProgRouter source currently verified for method guidance is the
arXiv preprint `2608.25992` (2026-08-26). This directory does not claim an exact
official reproduction and does not claim a conference acceptance.
