# 400题后续阶段草案

原400题全为MMLU-Pro；本草案为混合面板，160选择题、80数学、80MBPP、80HumanEval。只使用原train、排除pilot的120个ID，选题不使用分数。尚未启动400题采样。

120题pilot完成后，先依据accuracy、strict unique wins、winner组合分布、Oracle−DatasetBest gap及路由绝对准确率决定模型池；按每模型5次重复估计质量均值与方差。再做折内Ridge及MA比较；不挑最佳seed，不用外折结果选超参数。

用户已授权400题utility→MA整体方向；当前需明确面板组成并完成模型池审查。不得将旧全MMLU400题结果当成本混合面板结果，也不能将旧双模型MA入口直接用于新多模型池。
