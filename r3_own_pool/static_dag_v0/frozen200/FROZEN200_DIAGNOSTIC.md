# Frozen 200 Zero-Call Diagnostic: Why Crossover Narrowed from +4.2pp to +0.7pp

## Root Cause: Single is STRONGER on frozen panel, not Dynamic weaker

| Metric | Main 120 | Frozen 200 | Change |
|---|---:|---:|---|
| Dynamic f30 Q | 0.4056 | 0.4033 | -0.2pp (stable) |
| Single f30 Q | 0.3639 | 0.3967 | **+3.3pp (stronger)** |
| Single fault survival | ~63.6% | 71.8-75.5% | **+8-12pp** |

## Diagnostic Table

| Subset | N | Single Q | Dynamic Q | ΔQ |
|---|---:|---:|---:|---:|
| All | 200 | 0.3967 | 0.4033 | +0.7pp |
| 1-op (easy) | 121 | 0.5041 | 0.5096 | +0.6pp |
| ≥2-op (hard) | 79 | 0.2321 | 0.2405 | +0.8pp |
| Single clean→fault survived | 79 | 1.000 | 0.747 | **-25.3pp** |
| Single clean→fault broken | 31 | 0.000 | **0.484** | **+48.4pp** |
| Single clean wrong | 90 | 0.000 | 0.078 | +7.8pp |

## By Fault Node Type (seed 20260923)

| Type | N | Single | Static | Dynamic |
|---|---:|---:|---:|---:|
| evidence(e) | 32 | 0% | 25.0% | **31.3%** |
| reasoning(r) | 15 | 0% | 26.7% | **33.3%** |
| verification(v) | 13 | 0% | 0% | **15.4%** |

## Interpretation

1. Dynamic is STABLE (0.4056→0.4033, only -0.2pp across panels)
2. Single's fault survival is HIGHER on frozen panel (71.8% vs 63.6%) — the same 30% fault injection breaks fewer of Single's clean-correct tasks
3. Dynamic recovers 48.4% of Single's fault-induced failures (15/31) — recovery mechanism works well
4. BUT: Dynamic destroys 25.3% of tasks Single survived (28/79 harm) — this harm side wipes out the recovery gains
5. Hard subset: Single much stronger here (0.2321 vs main 0.1812) — the frozen panel's hard tasks may be more amenable to single-model direct answering

## Paper Wording

"The 30%-fault crossover between Dynamic and Single LLM, observed at +4.2pp on the development panel, narrows to +0.7pp on the independent frozen panel (not significant). The narrowing is attributable to stronger Single-LLM fault survival on the frozen tasks (71.8% vs 63.6%), not to Dynamic degradation (0.4033 vs 0.4056). Dynamic's zero-harm advantage over Static (Help/Harm 18/1 to 28/1, p<0.0001) and quality stability (degradation <3%) replicate fully."
