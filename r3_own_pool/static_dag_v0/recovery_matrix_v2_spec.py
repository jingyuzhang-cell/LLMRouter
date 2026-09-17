/**E8 recovery matrix v2 spec (frozen 2026-09-17).*/
CORE = '同一样本多动作配对测试：每个失败节点分别执行各恢复动作，其他条件固定。'
MIN_N = 150
TARGET_N = 200
ACTIONS = ['no_recovery', 'retry_same', 'switch_model', 'evidence_retrieval', 'local_decompose']
FAILURE_TYPES = ['evidence', 'reasoning', 'structural', 'parse']
# evidence_retrieval: 重新定位表格区域+定向选取相关行（非简单重调LLM抽取），后续推理模型固定
