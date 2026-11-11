# 第五次启动归档：确定性逐字检查缺NFKC（2026-11-11）

核验器v2判阶已正确（拟/终与文书语境一致），但verify_g7_terminal的确定性预检
re.sub(r'\s+')未做NFKC——docs_norm为SC.norm_text(NFKC)口径，含兼容字符的引文全部误判
'引文非被引文书逐字原文'（离线验证：raw全False/NFKC全True），13/14幻影失败耗尽重锚定预算。

修复：预检改R.SC.norm_text(quote)（与冻结evidence_rows同口径）。偏差链第4条：
implfail_v1→interrupted_v2→verifier_v1→verbatim_v1，全部实现层，预注册/Gold未动。
损耗：约16调用记账于此。
