# V1.8.2 独立复现命令

所有命令在 `/root/research_outputs/static_pi/stage_d` 执行；均为零调用，SYNTHETIC。

```bash
cd /root/research_outputs/static_pi/stage_d
python3 -u rq1_v1_8_2_joint_power.py > RQ1_V1_8_2_JOINT_LOG.log 2>&1
python3 rq1_v1_8_1_calibration.py > RQ1_V1_8_1_CALIBRATION.log 2>&1
python3 rq1_tasks/check_materials_v1_5.py
python3 rq1_tasks/check_gold_spans.py
python3 rq1_v1_7_plan_power.py > RQ1_V1_7_PLAN_POWER.log 2>&1
```

- 固定种子：V1.8.2 joint=20261107（scenarios seed 21–30）；V1.8.1=20261106；V1.8=20261105；V1.7=20261104。
- 预期输出：H0 FP≈0.045；H1 0.15 理想≈0.98；上游+解析≈0.67；方向≈0.075（以完整 50k/20k 日志为准）。
- 运行时：50k H0 约 630s；9×20k 合计约 40–50 分钟。
- 不做真实 API 调用；不恢复 192。
