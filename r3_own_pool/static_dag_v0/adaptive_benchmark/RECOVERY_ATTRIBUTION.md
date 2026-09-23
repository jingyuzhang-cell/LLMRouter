# Recovery Attribution Analysis (paper Table 3)

Success = Detection x Repairability x Execution — each row quantifies the factors by failure type.

## A. Clean scenario: initially-wrong tasks under Dynamic (corrected RD arm)

N = 78 initially-wrong tasks (fixed parser); recovery = task ends correct under RD.

| Failure type (primary, topological) | n | node detection | any detection | recovery success |
|---|---:|---:|---:|---:|
| evidence (parse/empty) | 44 | 100% | 100% | 16% (7/44) |
| evidence (wrong values) | 8 | 0% | 100% | 12% (1/8) |
| execution (r) | 4 | 100% | 100% | 0% (0/4) |
| reasoning (r) | 20 | 0% | 100% | 0% (0/20) |
| verification (v) | 2 | 100% | 100% | 0% (0/2) |

## B. Fault scenarios: injected faults, Dynamic recovery vs Static survival

### fault 10%
| Faulted node type | n | Dynamic recovery | Static survival |
|---|---:|---:|---:|
| evidence (injected e) | 7 | 29% | 0% |
| execution (injected r) | 4 | 75% | 50% |
| verification (injected v) | 1 | 100% | 0% |

### fault 20%
| Faulted node type | n | Dynamic recovery | Static survival |
|---|---:|---:|---:|
| execution (injected r) | 9 | 33% | 22% |
| evidence (injected e) | 10 | 50% | 10% |
| verification (injected v) | 5 | 40% | 0% |

### fault 30%
| Faulted node type | n | Dynamic recovery | Static survival |
|---|---:|---:|---:|
| execution (injected r) | 11 | 55% | 45% |
| evidence (injected e) | 15 | 40% | 7% |
| verification (injected v) | 10 | 40% | 0% |

## C. Verifier set: reasoning errors made detectable

signal fired 34 times; true reasoning errors 28 (detection precision 82%); repaired 7 (repair rate 21%).

Reading: execution-level failures are detected and partly repaired; evidence-value and reasoning failures are detected only partially (verifier adds 82%-precision reasoning detection) but their repair rate is the bottleneck — the ceiling is model capability on decomposed subtasks, not diagnosability.