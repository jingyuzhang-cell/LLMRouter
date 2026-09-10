# MA repeat-label controls

Mode: baseline. Original-train OOF development only.

| Arm | Quality | Versus DatasetBest | Wins/losses |
|---|---:|---:|---:|
| old_winner_all_seed42 | 83.529% | -3.597 pp | 23/130 |
| old_winner_all_seed43 | 83.563% | -3.563 pp | 21/127 |
| old_winner_all_seed44 | 83.630% | -3.496 pp | 21/125 |
| old_pair_panel_seed42 | 87.429% | +0.303 pp | 22/13 |
| old_pair_panel_seed43 | 87.126% | +0.000 pp | 16/16 |
| old_pair_panel_seed44 | 87.395% | +0.269 pp | 28/20 |
| RidgeGuard | 87.126% | +0.000 pp | 0/0 |

Stable-label arms NOT RUN: repeat labels required.
See TRACE.json for class coverage and fallback; a fallback is not evidence of learned MA benefit.
