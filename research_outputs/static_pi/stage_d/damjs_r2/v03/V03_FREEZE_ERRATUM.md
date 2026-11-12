# V03_FREEZE 勘误（2026-11-07）

`V03_FREEZE.json` 登记的 `damjs_r2/v03/V03_VALIDATION_RESULTS.json` SHA `8a883c1f8d76cf85…`（13:00 首轮通过后的版本）
已于 18:11 被试点接线验收 `test_v03_pilot.py` 的 A0 子测试重跑机制套件时覆写，原字节无备份、不可恢复。

- 现文件 SHA `5d3bbaf55d27d7ee…`：同一套件 `test_damjs_v03.py`（代码未改）的重跑结果，7/7 通过、网络尝试 0、
  预注册 SHA 一致（a173154d）；与原版的差异仅为运行事件时间戳/墙钟等非判定字段。
- 首轮失败记录 `V03_VALIDATION_RESULTS.attempt1.json` 未受影响。
- 原因：A0 直接调用会写归档文件的套件。已修正：A0 现在先备份、运行后逐字节还原归档文件，重跑输出另存
  `PILOT_ACCEPTANCE_A0_RERUN.json`。
- `V03_FREEZE.json` 原文不改；以本勘误为准。验证结论（7/7）不变。
