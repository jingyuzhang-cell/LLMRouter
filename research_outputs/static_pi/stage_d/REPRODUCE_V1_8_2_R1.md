# V1.8.2-R1 复现命令

```bash
cd /root/research_outputs/static_pi/stage_d
# 1) 联合验收（并行；50k H0 + 10×20k；约 10 分钟）
python3 -u rq1_v1_8_2_r1_parallel.py > RQ1_V1_8_2_R1_JOINT_LOG.log 2>&1
# 2) 方向可识别性（约 7 分钟）
python3 -u rq1_v1_8_2_r1_direction.py > RQ1_V1_8_2_R1_DIRECTION_LOG.log 2>&1
# 3) 方向 vs 测量预算
python3 -u rq1_v1_8_2_r1_direction2.py > RQ1_V1_8_2_R1_DIRECTION_REPS_LOG.log 2>&1
# 4) 精确检验回归（与暴力枚举对照，2,000 例含并列/零差）
python3 - <<'PY'
import numpy as np, itertools, random
# exact_p 定义见 rq1_v1_8_2_r1_joint.py；对照 brute 见 R1_AUDIT
PY
```
- 种子：joint=20261108（scenarios 101–111）；direction=20261109（200+）；reps=300+。
- 全部 SYNTHETIC；无 API 调用；不恢复 192。
