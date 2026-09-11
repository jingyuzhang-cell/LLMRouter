# P1：400题ΔQ可学习性

这是选题面板的开发诊断，尚未训练MA。

{
  "n": 400,
  "delta_greater_than_point2": 73,
  "delta_less_than_minus_point2": 51,
  "abs_delta_at_most_point05": 188,
  "exact_zero": 188,
  "quantiles": {
    "min": -1.0,
    "p10": -0.4,
    "p25": 0.0,
    "median": 0.0,
    "p75": 0.2,
    "p90": 0.6,
    "max": 1.0
  },
  "note": "Five binary repeats give empirical delta in increments of .2; observed tie does not imply equal expected quality.",
  "repeated_mean_sampling_variance": 0.037250000000000005,
  "posterior_ci_excludes_zero": 29,
  "posterior_caveat": "Monte Carlo under independent Beta(1,1) priors; descriptive uncertainty, never used to filter training labels."
}

| 基线 | MSE | MAE | R² | Spearman | AUC (nonzero ΔQ) |
|---|---:|---:|---:|---:|---:|
| TaskConstant | 0.12111 | 0.23784 | -0.002786337179651932 | -0.062470157898192304 | 0.47010869565217395 |
| SubjectMeanShrink20 | 0.12469 | 0.24401 | -0.03238062519469964 | -0.08858979648799513 | 0.4253170289855073 |
| GTE_Ridge1 | 0.11812 | 0.24673 | 0.02204369721722499 | 0.14498435993599776 | 0.6033514492753623 |
| GTE_Ridge20 | 0.12032 | 0.23748 | 0.003772932524062189 | 0.058041793180084546 | 0.5456521739130435 |
| RandomDelta_seed42 | 0.24300 | 0.36500 | -1.0119599843514226 | -0.004898948914369042 | 0.48704710144927527 |
| RandomDelta_seed43 | 0.22960 | 0.36500 | -0.9010123967369819 | 0.051204566777090864 | 0.5405344202898551 |
| RandomDelta_seed44 | 0.23830 | 0.36050 | -0.973045531979194 | 0.07372152069910518 | 0.5560688405797102 |

前2次/后3次ΔQ相关系数：0.550171767179025。
GTE_Ridge1优于20/20个学科内打乱标签对照。
开发信号门禁：True。门禁通过也不自动启动MA。

## Shuffle Label controls

Held-fold targets remain unchanged; only training labels are shuffled. Within-subject controls preserve subject signal, so their Spearman need not be zero. Global controls may also fluctuate around chance in this small selected panel.

| Control | Mean MSE | Mean Spearman | Mean AUC |
|---|---:|---:|---:|
| Within subject | 0.12640070784083798 | -0.008834955903763774 | 0.48872282608695655 |
| Global | 0.1262199995860977 | -0.0016058229115709362 | 0.5001539855072463 |

AUC excludes observed ties and is auxiliary; 0.65/0.75 are not proof thresholds or MA gates. All ties remain in regression. Neither a two-sided empirical distribution nor a nonzero shuffled correlation alone proves compatibility or leakage.
