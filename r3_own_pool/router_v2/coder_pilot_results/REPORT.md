# Coder 120题模型池筛查

| 模型 | Accuracy | 全五模型独有正确 |
|---|---:|---:|
| medium | 75.83% | 2/120 |
| large | 80.83% | 2/120 |
| glm | 44.17% | 1/120 |
| coder | 68.33% | 1/120 |
| reasoning | 82.50% | 4/120 |

| 模型池 | Oracle | DatasetBest | Ridge | Oracle gap |
|---|---:|---:|---:|---:|
| old_pair | 86.67% | 83.33% | 84.17% | 3.33% |
| historical_three | 88.33% | 85.00% | 83.33% | 3.33% |
| with_glm_four | 89.17% | 85.00% | 83.33% | 4.17% |
| coder_three | 87.50% | 81.67% | 82.50% | 5.83% |
| coder_four | 89.17% | 85.00% | 83.33% | 4.17% |
| all_five | 90.00% | 85.00% | 83.33% | 5.00% |

Coder does not pass >10% strict unique-win screening; inspect per-task gains and absolute routing quality before choosing a pool.

赢家组合分布、分任务准确率和区间见RESULTS.json。没有自动扩大样本或启动MA；先根据筛查结果冻结模型池及400题协议。
