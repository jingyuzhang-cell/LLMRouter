# GPU_AVAILABILITY_AUDIT — 宿主 GPU 可用性审计（零付费诊断）

## 诊断结果（2026-10-13）
| 检查项 | 结果 |
|---|---|
| nvidia-smi | "No devices were found" |
| /dev/nvidia0 | **缺失**（仅存 nvidiactl / nvidia-uvm 控制节点） |
| PCI 层 | /proc/bus/pci/devices 有 8 条 NVIDIA 记录（**宿主仍有卡**） |
| 驱动 | NVIDIA 580.76.05 已加载（open kernel module） |
| CUDA_VISIBLE_DEVICES | 空（未显式屏蔽） |
| 容器 | autodl-container-024b4f8aa7-7660f85b（AutoDL 实例） |

## 结论
**容器级 GPU 设备映射丢失，非驱动或代码问题**——与 AutoDL "无卡模式开机"特征一致
（该模式仅映射控制节点、不映射 /dev/nvidia0）。本会话早期 GPU 可见（RTX 4090 24GB），
说明实例运行状态中途发生变更（宿主迁移或无卡重启）。

## 恢复路径（平台侧操作，按指令不由执行层代做）
用户在 AutoDL 平台将实例**关机后以 GPU 模式重启**即可恢复映射；恢复后本地
Qwen2.5-7B/14B（权重与启动脚本在库）和 gte-Qwen2 嵌入即可用。当前轮一切方案
按**无 GPU 环境**设计（云端 API 路线），本地模型列为恢复后增强项。
