# LLMRouter：面向大语言模型智能路由的统一开源框架

## 摘要

随着大语言模型（LLM）生态的蓬勃发展，不同规模、能力和成本的模型层出不穷。如何根据查询的复杂度和用户需求，动态选择最合适的模型，成为一个关键的研究问题。本文系统性地介绍了 LLMRouter——一个面向 LLM 智能路由的统一开源框架。LLMRouter 集成了超过 16 种路由策略，涵盖单轮路由、多轮路由、个性化路由和代理路由四大类别，实现了从 KNN、SVM、MLP 等传统机器学习方法到图神经网络（GNN）、双对比学习（Dual Contrastive Learning）、矩阵分解（Matrix Factorization）和 Elo 评级等前沿路由算法。该框架提供完整的数据生成管线（支持 11 个标准评测基准）、统一命令行接口、Gradio 交互式聊天界面、ComfyUI 可视化工作流、插件化自定义路由器系统、以及兼容 OpenAI API 的生产级部署服务器。本文详细阐述了 LLMRouter 的系统架构、各类路由器的数学原理与实现细节、数据管线的设计、训练与推理流程、评估体系以及生产部署方案，并对框架的优势、局限和未来发展方向进行了深入讨论。

**关键词**：大语言模型路由；模型选择；智能路由；开源框架；成本优化；多目标优化

---

## 1. 引言

### 1.1 研究背景

近年来，大语言模型（Large Language Models, LLMs）领域经历了前所未有的繁荣。从 GPT-4、Claude 等闭源商业模型，到 Llama、Qwen、Mistral 等开源模型，不同规模（从 1B 到 405B+）和能力的 LLM 层出不穷。这种多样性为用户提供了丰富的选择，但也带来了一个核心挑战：**对于给定的查询，应该选择哪个模型？**

这个问题并非简单的"选最好的模型"。实践中，模型选择需要在多个相互冲突的目标之间权衡：

1. **回答质量**：更大的模型通常提供更高质量的回答，但并非所有查询都需要顶尖模型
2. **调用成本**：大模型的 API 调用成本可能是小模型的数十甚至上百倍
3. **响应延迟**：大模型的推理延迟显著高于小模型
4. **可靠性**：不同模型在不同类型任务上的表现差异显著

一个理想的 LLM 路由系统应该能够像"智能调度员"一样，根据每个查询的特征（复杂度、领域、长度等），自动将查询分配给最合适的模型，在满足质量要求的前提下最小化成本和延迟。

### 1.2 现有工作的局限

学术界和工业界已经提出了多种 LLM 路由方法，例如：

- **RouteLLM** (ICLR 2025)：基于偏好数据学习路由决策
- **RouterDC** (NeurIPS 2024)：基于双对比学习的查询路由器
- **AutoMix** (NeurIPS 2024)：自动混合大小模型的策略
- **Hybrid LLM** (ICLR 2024)：成本效率与质量感知的路由
- **GraphRouter** (ICLR 2025)：基于图神经网络的路由选择
- **Router-R1** (NeurIPS 2025)：通过强化学习实现多轮路由与聚合

然而，这些工作存在一个共同问题：**各自独立实现，缺乏统一的框架和标准化的对比基准**。研究者和开发者若想对比不同路由方法，需要分别复现各个方法，这极大地阻碍了领域的进展。

### 1.3 LLMRouter 的贡献

LLMRouter 旨在填补这一空白，其主要贡献包括：

1. **统一框架**：将 16+ 种路由策略整合到单一框架中，提供标准化的训练、推理和评估接口
2. **完整的数据管线**：支持从 11 个标准评测基准自动生成路由训练数据，包括多模态任务
3. **多层次抽象**：通过 MetaRouter 基类和 BaseTrainer 基类，实现路由决策与模型训练的清晰分离
4. **插件化架构**：支持零侵入式地添加自定义路由器，无需修改核心代码
5. **生产级部署**：提供兼容 OpenAI API 的服务器，支持流式响应、WebSocket、多平台集成
6. **丰富的用户界面**：包括 CLI 命令行、Gradio 网页聊天、ComfyUI 可视化工作流

---

## 2. 系统架构

### 2.1 总体架构

LLMRouter 采用分层架构设计，自上而下分为六个层次：

```
┌──────────────────────────────────────────────────────────────┐
│                      用户界面层                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ CLI 命令  │  │  Gradio  │  │ ComfyUI  │  │ OpenAI API   │ │
│  │          │  │  聊天界面 │  │ 可视化节点│  │  兼容服务器   │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘ │
├──────────────────────────────────────────────────────────────┤
│                      路由决策层                                │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Plugin System (插件发现与注册)              │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐     ┌──────────┐  │   │
│  │  │KNN路由 │ │MLP路由 │ │GNN路由 │ ... │ 自定义路由 │  │   │
│  │  └────────┘ └────────┘ └────────┘     └──────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────┤
│                      模型抽象层                                │
│  ┌──────────────────────────────────────────────────────┐   │
│  │   MetaRouter (nn.Module + ABC)  ← 统一基类             │   │
│  │   BaseTrainer (ABC)             ← 训练逻辑基类          │   │
│  └──────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────┤
│                      数据与评估层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ 数据生成  │  │ 数据加载  │  │ API调用  │  │ 性能评估  │   │
│  │ Pipeline  │  │ DataLoader│  │ API Caller│  │ Evaluator │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
├──────────────────────────────────────────────────────────────┤
│                      基础设施层                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ 嵌入生成  │  │ Prompt模板│  │ 模型持久化│  │ 工具函数  │   │
│  │Embeddings│  │ Prompting │  │ Save/Load│  │  Utils   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
├──────────────────────────────────────────────────────────────┤
│                      外部依赖层                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ PyTorch  │  │Transforme│  │ LiteLLM  │  │  FastAPI  │   │
│  │          │  │    rs    │  │          │  │  + Uvicorn│   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 核心抽象：MetaRouter

所有路由器的统一基类 `MetaRouter` 继承自 PyTorch 的 `nn.Module` 和 Python 的 `ABC`（抽象基类），确保每个路由器既是可训练的神经网络模块，又遵循统一的路由接口。

```python
class MetaRouter(nn.Module, ABC):
    def __init__(self, model: nn.Module, yaml_path: str | None = None, resources=None):
        # 1. 持有底层 PyTorch 模型
        # 2. 加载 YAML 配置文件
        # 3. 通过 DataLoader 加载训练/测试数据
        # 4. 附加数据集到实例属性:
        #    - self.query_data_train / self.query_data_test
        #    - self.routing_data_train / self.routing_data_test
        #    - self.llm_data
        #    - self.query_embedding_data

    @abstractmethod
    def route_single(self, query_input: dict) -> dict:
        """单条查询路由"""

    @abstractmethod
    def route_batch(self, batch) -> list:
        """批量查询路由"""

    def forward(self, batch):
        """PyTorch 前向传播，默认委托给 route_batch()"""
        return self.route_batch(batch)
```

这一设计的核心思想是：

- **`route_single`** 和 **`route_batch`** 是路由器的对外接口，返回包含 `model_name` 字段的字典
- **`forward`** 是 PyTorch 兼容的训练接口，使路由器可以像普通 nn.Module 一样参与训练循环
- **配置加载** 在初始化时自动完成，子类无需关心数据加载细节

### 2.3 训练抽象：BaseTrainer

训练逻辑通过 `BaseTrainer` 基类与路由器解耦：

```python
class BaseTrainer(ABC):
    def __init__(self, router, optimizer=None, device="cpu"):
        self.router = router        # 关联的路由器实例
        self.optimizer = optimizer  # PyTorch 优化器
        self.device = device        # 训练设备

    def loss_func(self, **kwargs):
        """损失函数（子类可覆盖）"""

    @abstractmethod
    def train(self):
        """训练逻辑（子类必须实现）"""
```

每个可训练的路由器都有对应的 Trainer 类（如 `KNNRouterTrainer`、`MLPRouterTrainer`），负责实现具体的训练算法。这种分离设计使得：

- 路由器代码专注于推理决策
- 训练器代码专注于参数优化
- 推理和训练可以独立演化和测试

### 2.4 插件系统

插件系统（`plugin_system.py`）支持零侵入式添加自定义路由器，自动发现路径包括：

1. `./custom_routers/` — 项目目录（推荐方式）
2. `~/.llmrouter/plugins/` — 用户主目录
3. `$LLMROUTER_PLUGINS` — 环境变量指定路径

插件发现机制通过 Python 的动态导入（`importlib`）扫描子目录，查找符合接口规范的路由器类，自动验证并注册到系统中。注册后的自定义路由器与内置路由器使用方式完全一致。

---

## 3. 数据管线

### 3.1 数据生成流程

LLMRouter 的完整数据管线包含三个步骤：

#### 第一步：查询数据生成 (`data_generation.py`)

从 HuggingFace 数据集提取查询样本，生成训练/测试分割的 JSONL 文件。支持的 11 个评测基准包括：

| 类别    | 数据集                         | 评估指标             |
| ----- | --------------------------- | ---------------- |
| 知识问答  | Natural Questions, TriviaQA | Exact Match      |
| 多领域理解 | MMLU                        | Exact Match (MC) |
| 科学推理  | GPQA                        | Exact Match      |
| 数学推理  | GSM8K, MATH                 | 数值匹配             |
| 代码生成  | MBPP, HumanEval             | 执行验证             |
| 常识推理  | CommonsenseQA               | Exact Match      |
| 阅读理解  | OpenbookQA, ARC-Challenge   | Exact Match      |

此外，还支持 **5 个多模态任务**（Geometry3K, MathVista, Charades-Ego 的活动/物体/动词识别），通过 VLM 进行图像/视频描述生成。

配置文件（YAML）示例：

```yaml
datasets:
  - name: "gsm8k"
    split: "train"
    num_samples: 500
  - name: "mmlu"
    config_name: "all"
    split: "test"
    num_samples: 200
output:
  train_path: "data/query_data/query_data_train.jsonl"
  test_path: "data/query_data/query_data_test.jsonl"
```

#### 第二步：LLM 嵌入生成 (`generate_llm_embeddings.py`)

为候选 LLM 生成嵌入向量。输入为 `default_llm.json`，包含每个模型的元数据（名称、规模、特征描述、价格等）：

```json
{
  "qwen2.5-7b-instruct": {
    "size": "7B",
    "feature": "Qwen2.5-7B-Instruct, strong at general reasoning and instruction following",
    "input_price": 0.0,
    "output_price": 0.0,
    "model": "qwen/qwen2.5-7b-instruct",
    "service": "NVIDIA",
    "api_endpoint": "https://integrate.api.nvidia.com/v1"
  }
}
```

使用 Longformer 模型对 `feature` 字段进行编码，生成每个模型的嵌入向量，输出为 `default_llm_embeddings.json`。

#### 第三步：API 调用与评估 (`api_calling_evaluation.py`)

这是管线中最关键的步骤：

1. **并行 API 调用**：使用所有候选 LLM 回答所有查询，支持多 API Key 轮转负载均衡
2. **性能评估**：根据每个任务的评估指标计算模型的回答质量分数（0.0-1.0）
3. **统一嵌入生成**：为每个查询生成 Longformer 嵌入，分配唯一 `embedding_id`
4. **路由数据输出**：生成格式化的路由训练数据 JSONL

路由数据条目的格式：

```json
{
  "task_name": "gsm8k",
  "query": "Janet has 4 apples. She gives 2 to Bob. How many does she have left?",
  "ground_truth": "2",
  "metric": "GSM8K",
  "model_name": "llama3-chatqa-1.5-8b",
  "response": "Janet has 4 apples... so she has 4 - 2 = 2 apples left.",
  "performance": 1.0,
  "embedding_id": 42,
  "token_num": 453
}
```

### 3.2 数据加载器

`DataLoader` 类负责从 YAML 配置文件中的路径加载所有数据，并将其作为属性附加到路由器实例上。关键数据包括：

- **`query_data_train/test`**：待路由的查询列表
- **`routing_data_train/test`**：模型在查询上的历史表现数据
- **`llm_data`**：候选 LLM 的元数据字典
- **`query_embedding_data`**：查询嵌入向量（PyTorch 张量列表）

### 3.3 嵌入系统

嵌入生成（`embeddings.py`）使用 Longformer 模型将文本查询转换为固定长度的向量表示：

```
q = Longformer(query_text)  ∈ ℝ^768
```

该系统具有以下特性：

- **自动设备检测**：支持 CUDA、MPS 和 CPU
- **懒加载初始化**：首次使用时才加载模型
- **离线下退**：通过环境变量可切换为哈希模式（用于无 GPU 环境测试）
- **批量处理**：支持批量编码以提高效率

---

## 4. 路由策略详解

LLMRouter 按照路由决策的复杂度和交互模式，将 16+ 种路由器分为四大类。以下对每类中的代表性路由器进行数学原理和实现细节的深入阐述。

---

### 4.1 单轮路由器（Single-Round Routers）

单轮路由器仅根据当前查询本身的特征做出路由决策，不依赖对话历史。这类路由器训练成本低、推理速度快，适合大多数独立查询场景。

#### 4.1.1 KNNRouter — K近邻路由器

**原理**：基于历史数据中与当前查询最相似的 K 个查询的路由选择来投票决定。

**数学模型**：

给定训练数据 D = {(q_i, m_i, p_i)}，其中 q_i 为查询，m_i 为被调用的模型，p_i 为性能得分。

1. **嵌入映射**：使用 Longformer 将查询映射为向量
   
   ```
   v = Longformer(q)  ∈ ℝ^768
   ```

2. **距离计算**：对于新查询 q_new，计算其与所有历史查询的距离
   
   ```
   d(q_new, q_i) = ||v_new - v_i||_2  （欧几里得距离）
   ```
   
   或使用余弦相似度：
   
   ```
   sim(q_new, q_i) = (v_new · v_i) / (||v_new|| × ||v_i||)
   ```

3. **训练数据准备**：对于每个查询，选择性能最好的模型作为标签
   
   ```
   label(q) = argmax_{m} performance(q, m)
   ```

4. **KNN 分类**：使用 sklearn 的 `KNeighborsClassifier`，对新查询找到 K 个最近邻
   
   ```
   model_name = KNN.predict(v_new)  = mode({label(N_i) : i=1,...,K})
   ```

**可配置超参数**：

- `n_neighbors`：邻居数量 K（默认 5）
- `metric`：距离度量方式（"cosine"、"euclidean" 等）
- `weights`：投票权重（"uniform" 或 "distance"）

**训练流程**：

1. 加载路由数据，对每个查询选择表现最好的模型
2. 提取查询嵌入向量作为特征矩阵 X
3. 最优模型名称作为标签 y
4. 使用 sklearn KNeighborsClassifier 拟合并保存模型

#### 4.1.2 SVMRouter — 支持向量机路由器

**原理**：在查询嵌入空间中学习决策边界，将不同模型"最适合"的查询区域分开。

**数学模型**：

SVM 解决以下优化问题（以线性核为例）：

```
min_{w, b, ξ}  ½||w||² + C Σᵢ ξᵢ
s.t.  yᵢ(w^T xᵢ + b) ≥ 1 - ξᵢ,  ξᵢ ≥ 0
```

在多类别场景中，使用 One-vs-Rest 策略：

- 为每个候选模型训练一个二分类器
- 新查询分配给决策函数值最大的模型

**特点**：

- 在小样本数据集上表现良好
- 通过核函数（RBF、多项式等）可以处理非线性决策边界
- C 参数控制正则化强度，平衡经验风险与模型复杂度

#### 4.1.3 MLPRouter — 多层感知机路由器

**原理**：使用前馈神经网络学习查询嵌入到模型选择的非线性映射。

**网络结构**：

```
Input (768) → Linear → ReLU → Linear → ReLU → ... → Linear → Output (num_models)
```

**数学模型**：

单层前向传播：

```
h^(1) = σ(W^(1) x + b^(1))
h^(2) = σ(W^(2) h^(1) + b^(2))
...
z = W^(L) h^(L-1) + b^(L)
p(m|x) = softmax(z)_m
```

其中 σ 为激活函数（ReLU、tanh、sigmoid 或 identity），L 为隐藏层数。

**损失函数**（交叉熵）：

```
L = -Σᵢ log p(m_i| x_i)
```

**训练**：

- 使用 PyTorch 原生实现（非 sklearn），支持 GPU 加速
- 向后兼容 sklearn 格式的旧模型文件
- 支持 L2 正则化（weight decay）
- 输出为每个模型的概率分布

**可配置超参数**：

- `hidden_layer_sizes`：隐藏层大小列表（如 [128, 64]）
- `activation`：激活函数类型
- `lr`：学习率
- `epochs`：训练轮数
- `batch_size`：批次大小
- `alpha`：L2 正则化系数

#### 4.1.4 MFRouter — 矩阵分解路由器

**原理**：将"查询"和"模型"映射到同一个隐空间（latent space），通过隐空间中查询嵌入与模型嵌入的内积来衡量匹配度。该方法受 RouteLLM 的启发。

**数学模型**：

1. **模型嵌入**：每个模型有一个可学习的隐向量
   
   ```
   P = [v_1, v_2, ..., v_M]^T  ∈ ℝ^{M × d}
   ```
   
   其中 M 为模型数量，d 为隐空间维度。

2. **查询投影**：将 Longformer 嵌入投影到隐空间
   
   ```
   proj(q) = W_text · Longformer(q)  ∈ ℝ^d
   ```
   
   其中 W_text ∈ ℝ^{d × 768}

3. **评分函数**：Bilinear MF（双线性矩阵分解）
   
   ```
   δ(m, q) = w_2^T (v_m ⊙ (W_1 · v_q))
   ```
   
   其中 ⊙ 表示逐元素乘积（Hadamard product）

4. **路由决策**：
   
   ```
   best_model = argmax_m δ(m, q)
   ```

**训练方式（成对比较）**：

与直接拟合性能分数不同，MFRouter 使用成对比较损失。对于每个查询，构建 (winner, loser) 对：

```
L = -Σ_{(q, w, l)} log σ(δ(w, q) - δ(l, q))
```

其中 σ 为 sigmoid 函数，w 为性能更好的模型，l 为性能较差的模型。这种损失函数更关注相对排序而非绝对分数。

#### 4.1.5 EloRouter — Elo评级路由器

**原理**：将竞技游戏中的 Elo 评级系统引入模型路由。每个模型被赋予一个评分，通过在"比赛"（即在相同查询上的表现对比）中的胜负结果动态更新。

**数学模型**：

1. **比赛构建**：对于每个查询，将表现最好的模型（winner）与其他每个模型（loser）组成比赛对，包括正向和反向：
   
   ```
   Battles = {(winner, loser, label=1)} ∪ {(loser, winner, label=0)}
   ```

2. **Elo 评分估计**：使用逻辑回归的最大似然估计（MLE）计算 Elo 分
   
   ```
   X_{ij} = log(BASE)  （行 i 的 model_a）
   X_{ij} = -log(BASE) （行 i 的 model_b）
   Y_i = 1[winner = model_a]
   
   min_β -Σ_i [Y_i log(σ(X_i β)) + (1-Y_i) log(1-σ(X_i β))]
   ```

3. **最终评分**：
   
   ```
   Elo_m = SCALE × β_m + INIT_RATING
   ```
   
   默认参数：SCALE = 400, BASE = 10, INIT_RATING = 1000

4. **路由决策**：
   
   ```
   best_model = argmax_m Elo_m
   ```

**特点**：

- 全模型共享评分，查询无关（global ranking）
- 训练极快（逻辑回归，无迭代）
- 对新模型的冷启动：可直接赋予初始评分

#### 4.1.6 DCRouter — 双对比学习路由器

**原理**：基于 RouterDC (NeurIPS 2024)，使用双对比学习（Dual Contrastive Learning）训练一个 DeBERTa 编码器，将查询文本和 LLM 描述文本映射到共享语义空间，通过查询-LLM 相似度进行路由。

**核心架构**：

1. **编码器**：基于 mDeBERTaV2 的文本编码器

2. **可训练的 LLM 嵌入**：每个候选 LLM 有一个可训练的嵌入向量

3. **三种对比损失**：
   
   **(a) 查询-LLM 对对比损失（QC Loss）**：
   
   ```
   L_QC = -log [ exp(sim(q, m⁺)) / Σ_{m} exp(sim(q, m)) ]
   ```
   
   拉近查询与最适合模型的嵌入距离。
   
   **(b) 查询-查询对比损失（QQ Loss）**：
   
   ```
   L_QQ = -log [ exp(sim(q, q⁺)) / Σ_{q'} exp(sim(q, q')) ]
   ```
   
   拉近路由到相同模型的查询嵌入。
   
   **(c) LLM-LLM 对比损失（MM Loss）**：
   
   ```
   L_MM = -log [ exp(sim(m, m⁺)) / Σ_{m'} exp(sim(m, m')) ]
   ```
   
   拉近在相似查询上表现好的模型嵌入。

4. **Sample-LLM 对比损失的具体实现**：
   
   ```
   L_sample_llm = -(1/|top_k|) Σ_{p ∈ top_k} log[ exp(s_p/t) / (exp(s_p/t) + Σ_{n ∈ neg_k} exp(s_n/t)) ]
   ```
   
   其中 top_k 为表现最好的 k 个 LLM（正样本），neg_k 为表现最差的 k 个 LLM（负样本），t 为温度参数。关键设计：
   
   - 通过遮罩排除 `true_score > 0.5` 的负样本（避免将"好"模型误当负样本）
   - LLM 嵌入使用正态分布 N(0, 0.78²) 初始化
   - 支持余弦相似度和内积两种相似度计算方式

5. **总损失**：
   
   ```
   L_total = L_sample_llm + λ₁ · L_sample_sample + λ₂ · L_cluster
   ```
   
   其中 λ₁ = `sample_loss_weight`，λ₂ = `cluster_loss_weight`，可在配置中调节各损失项的相对重要性。

**训练细节**：

- 优化器：AdamW，可配置学习率和权重衰减
- 训练步数驱动（非 epoch 驱动），支持跨 epoch 循环
- 梯度累积：支持多步梯度累积以增大有效批次大小
- 评估指标：路由准确率（argmax 匹配率）和任务准确率（二元阈值）
- 保存两个检查点：`best_model.pth`（最佳测试准确率）和 `best_training_model.pth`（最佳训练准确率）

**数据预处理**：DCRouter 使用单独的数据预处理流程（`dcdata_utils.py`），支持可选的聚类预处理（使用 `n_clusters` 参数），为每个查询生成正负样本对。

**推理流程**：

```
1. tokenize(query) → input_ids, attention_mask
2. backbone(input_ids) → [CLS] hidden_state
3. For each LLM m: score_m = similarity(hidden_state, llm_emb[m]) / temperature
4. best_model = argmax_m score_m
```

#### 4.1.7 AutoMix — 自动模型混合

**原理**：基于 AutoMix (NeurIPS 2024)，通过"先尝试小模型，必要时求助大模型"的策略来优化成本-质量权衡。使用验证器（verifier）判断小模型的回答是否需要"升级"到大模型。

**核心策略**：

1. **Threshold（阈值策略）**：当验证器置信度低于阈值 τ 时，升级到大模型
   
   ```
   route_to_llm(q) = 1[p_ver_slm(q) < τ]
   ```

2. **POMDP（部分可观测马尔可夫决策过程）**：将路由建模为 POMDP
   
   - 状态：查询特征
   - 动作：{使用小模型, 升级到大模型}
   - 观测：验证器得分
   - 奖励：性能提升 − 成本增加

3. **IBC Lift（增量效益-成本提升比）**：
   
   ```
   IBC_Lift = (AutoMix_Slope − SLM_LLM_Slope) / SLM_LLM_Slope
   ```
   
   其中：
   
   ```
   AutoMix_Slope = (Perf_automix - Perf_slm) / (Cost_automix - Cost_slm)
   SLM_LLM_Slope = (Perf_llm - Perf_slm) / (Cost_llm - Cost_slm)
   ```

4. **参数搜索**：遍历候选参数，选择 IBC Lift 最大的参数

**独特性**：AutoMix 是唯一一个同时考虑质量和成本多目标优化的路由器。

#### 4.1.8 HybridLLM — 混合LLM路由器

**原理**：基于 Hybrid LLM (ICLR 2024)，专门解决"小模型 vs 大模型"的二元路由问题。核心思想是训练一个 MLP 回归器来预测小模型相对大模型的性能差距。

**数学模型**：

1. **性能差距预测**：
   
   ```
   gap(q) = MLP(Longformer(q))  ∈ [0, 1]
   ```
   
   其中 gap 接近 1 表示小模型足以应对，接近 0 表示需要大模型。

2. **三种路由模式**：
   
   **(a) 确定性模式（Deterministic）**：
   
   ```
   label = 1[perf_small >= perf_large]
   ```
   
   **(b) 概率模式（Probabilistic）**：
   
   ```
   label = σ((perf_small - perf_large) / τ)
   ```
   
   其中 τ 为温度参数，控制路由的"软硬"程度。
   
   **(c) 变换模式（Transformed）**：
   
   ```
   label = 1[perf_small >= perf_large - t*]
   ```
   
   其中 t* 通过最大化标签平衡度来选择：
   
   ```
   t* = argmax_t 2p(t)(1-p(t)),  p(t) = mean(1[gap >= -t])
   ```

3. **路由决策**：
   
   ```
   chosen = small_model  if score >= threshold
   chosen = large_model  if score < threshold
   ```

#### 4.1.9 GraphRouter — 图神经网路路由器

**原理**：基于 GraphRouter (ICLR 2025)，将查询、LLM 和它们之间的关系建模为异构图（Heterogeneous Graph），使用图神经网络（GNN）进行路由决策。

**图结构**：

```
┌─────────┐          ┌─────────┐
│ Query 1 │──perf──▶│  LLM A  │
├─────────┤          ├─────────┤
│ Query 2 │──perf──▶│  LLM B  │
├─────────┤          ├─────────┤
│  ...    │          │  ...    │
├─────────┤          └─────────┘
│ Query N │
└─────────┘

节点类型：
  - 查询节点：特征为 Longformer 嵌入（归一化）
  - LLM 节点：特征为 LLM 嵌入向量（归一化）

边类型：
  - 每个查询连接到所有 LLM
  - 边特征：历史性能得分
```

**GNN 架构**：

1. **编码器-解码器结构**：
   
   ```
   h_query = Encoder_Q(query_feat, edge_info)
   h_llm = Encoder_M(llm_feat, edge_info)
   ```

2. **特征对齐**：将不同维度的查询特征和 LLM 特征映射到相同的隐藏空间
   
   ```
   W_Q: ℝ^{query_dim} → ℝ^{hidden_dim}
   W_M: ℝ^{llm_dim} → ℝ^{hidden_dim}
   ```

3. **广义图卷积（GeneralConv）**：
   
   ```
   h_v^(l+1) = σ(W^(l) h_v^(l) + Σ_{u∈N(v)} α_{vu} W_edge e_{vu} ⊙ h_u^(l))
   ```
   
   其中 α_{vu} 为注意力权重。

4. **边 MLP**：对每条边（查询-LLM 连接）计算最终的匹配分数
   
   ```
   score(q, m) = MLP_edge(h_q ⊕ h_m ⊕ e_qm)
   ```

5. **路由决策**：
   
   ```
   best_model = argmax_m score(q, m)
   ```

**回退机制**：当 PyTorch Geometric 不可用时，GraphRouter 提供了自定义的 GeneralConv 实现作为回退。

#### 4.1.10 CausalLMRouter — 因果语言模型路由器

**原理**：使用预训练的因果语言模型（如 BERT 变体）直接理解查询的深层语义，输出路由分类结果。

**核心设计**：

- 编码器使用预训练 transformer 模型
- 输出层将 [CLS] token 的表示映射到模型选择 logits
- 支持微调（fine-tuning）模式
- 对查询的语义理解比仅使用静态嵌入的 KNN/SVM/MLP 更深入

#### 4.1.11 基准路由器

**SmallestLLM**：总是选择最小的模型（按参数量排序），作为成本下界

**LargestLLM**：总是选择最大的模型，作为质量上界

这两个路由器不需要训练，仅依赖 `llm_data` 中的 `size` 字段进行模型排序。

---

### 4.2 多轮路由器（Multi-Round Routers）

多轮路由器维护整个对话的上下文，能够根据对话历史动态调整路由策略。

#### 4.2.1 RouterR1 — 强化学习多轮路由器

**原理**：基于 Router-R1 (NeurIPS 2025)，使用 vLLM 部署的大语言模型本身作为多轮路由决策器，通过强化学习训练模型进行任务分解、子任务分配和结果聚合。

**核心组件**：

1. **Prompt Pool（提示词池）**：存储多种路由提示模板，支持不同推理模式

2. **Route Service（路由服务）**：管理与外部模型路由池的通信
   
   - 提供 REST API `/get_available_models`
   - 返回可用模型的列表及其属性（能力描述、成本等）

3. **多步推理范式**：
   
   ```
   <search>
     分析当前查询
     拆解为子任务 [t1, t2, ..., tn]
     为每个子任务选择最佳模型
   </search>
   <answer>
     调用各模型获取子任务回答
     聚合子结果
     给出最终答案和路由理由
   </answer>
   ```

4. **自动 TP 检测**：根据模型头数自动计算张量并行度（tensor parallelism），优化 vLLM 部署

5. **Token 跟踪**：精确计算包括路由推理在内的总 token 消耗

**迭代路由算法**：

```
Algorithm: RouterR1 Agentic Routing Loop
Input: user_query, max_iterations=5
Output: final_answer, routing_trace

1. prompt ← PROMPT_TEMPLATE.format(user_query, available_llms)
2. for iteration = 1 to max_iterations:
3.     output ← vllm_generate(prompt, temp=1.0, max_tokens=1024,
4.                            stop=["</search>", "</answer>"])
5.     if "<search>LLM-Name:sub_query</search>" in output:
6.         llm_name, sub_query ← parse_search_tag(output)
7.         api_id, tau ← check_llm_name(llm_name)
8.         result ← get_llm_response_via_api(api_id, sub_query, tau)
9.         prompt ← prompt + "<information>" + result + "</information>"
10.        continue
11.    if "<answer>" in output:
12.        answer ← parse_answer_tag(output)
13.        break
14. return answer, trace
```

**外部模型解析**（`check_llm_name`）：

- "qwen" → `qwen/qwen2.5-7b-instruct`
- "llama" + "70b" → `meta/llama-3.1-70b-instruct`
- "llama" + "8b" → `meta/llama-3.1-8b-instruct`
- "mistral" → `mistralai/mistral-7b-instruct-v0.3`
- "mixtral" → `mistralai/mixtral-8x22b-instruct-v0.1`
- "gemma" → `google/gemma-2-27b-it`

**路由决策的独特性**：

- RouterR1 会产生详细的"思考链"，解释为什么将特定子任务分配给特定模型
- 支持"需要时再搜索"的延迟路由模式
- 路由器本身就是一个 LLM，具有推理能力，可以动态决定调用多少外部模型
- 使用 vLLM 张量并行（TP），自动检测最佳 TP 大小

#### 4.2.2 KNNMultiRoundRouter — KNN多轮路由器

**原理**：将复杂查询分解为多个子查询，对每个子查询独立使用 KNN 路由器进行选择，最后聚合结果。

**流程**：

```
1. 接收用户查询
2. 使用 LLM 拆解为子任务 [{sub_q1}, {sub_q2}, ...]
3. 对每个子任务独立运行 KNNRouter.route_single()
4. 聚合所有子任务的回答
5. 返回最终结果和路由跟踪
```

#### 4.2.3 LLMMultiRoundRouter — LLM多轮路由器

**原理**：直接使用 LLM 作为多轮路由的决策者（类似 RouterR1 的简化版），无需预训练路由器模型。

**特点**：

- 仅需推理，无需训练
- 使用 LLM 的语义理解能力进行任务分解和模型选择
- 适合快速实验和原型验证

---

### 4.3 个性化路由器（Personalized Routers）

个性化路由器考虑用户偏好和历史交互，为每个用户动态优化路由决策。

#### 4.3.1 GMTRouter — 图多轮个性化路由器

**原理**：基于 GMTRouter，将用户的多轮交互历史建模为异构图（Heterogeneous Graph），使用异构图变换器（HGT, Heterogeneous Graph Transformer）学习用户偏好，并结合当前查询进行个性化路由。

**图结构**（5 种节点类型、21 种边类型）：

```
节点类型：User, Session, Query, LLM, Response

边类型（21种）：
  1-2. User ↔ Session (user_own_session, session_owned_by_user)
  3-4. Session ↔ Query (session_has_query, query_in_session)
  5-6. Query ↔ Response (query_answered_by_response, response_answered_to_query)
  7-8. LLM ↔ Response (llm_generate_response, response_generated_by_llm)
  9-10. Session 时序 (session_next, session_prev)
  11-12. Query 时序 (query_next, query_prev)
  13-14. User → LLM 偏好 (user_prefer_llm, llm_preferred_by_user)
  15-16. Query 相似度 (query_similar_to_query)
  17-18. LLM 相似度 (llm_similar_to_llm)
  19-20. Response 质量 (response_high_quality, response_low_quality)
  21. User → Session (user_own_session)
```

**核心组件**：

1. **HeteroGNN**：使用 HGTConv 层的异构图神经网络
   
   ```
   h_v^(l+1) = LayerNorm(HGTConv(h_v^(l), {h_u^(l): u ∈ N(v)}, edge_types))
   ```
   
   包含节点投影层（将各类型节点的不同维度特征映射到统一隐藏空间）、多头注意力（num_heads=4）和残差连接

2. **PreferencePredictor**：基于交叉注意力的偏好评分器
   
   ```
   score = MLP(CrossAttention(query_emb, [user_emb, llm_emb]))
   ```
   
   将用户嵌入和 LLM 嵌入作为上下文，查询嵌入作为 query，通过多头交叉注意力计算匹配分数

3. **训练方式**：成对偏好学习
   
   ```
   L = BCE(σ(score_w − score_l), 1.0)
   ```
   
   每 epoch 采样 prediction_count=256 个成对比较，目标为最大化高评分模型的得分优势

**核心特点**：

- 用户节点嵌入编码长期偏好（通过零初始化 + GNN 消息传递学习）
- 时序边（session_next/prev, query_next/prev）编码交互历史的时间顺序
- 用户-LLM 偏好边从评分数据中提取（rating ≥ 4.0 时建立连接）
- Response 质量边根据评分将回答分为高质量和低质量

#### 4.3.2 PersonalizedRouter — GNN个性化路由器

**原理**：基于 PersonalizedRouter，使用图神经网络建模用户-查询-模型三方关系，通过 GNN 的消息传递机制融合用户特征。

**数据格式**：

```json
{
  "user_id": "user_123",
  "user_profile": {
    "preferred_models": ["model_a", "model_b"],
    "task_preferences": {"code": 0.8, "writing": 0.3},
    "cost_sensitivity": 0.7
  },
  "query": "...",
  "history": [...]
}
```

**GNN 结构**（`graph_nn.py`）：

- 用户嵌入层：将用户特征映射到隐空间
- 查询编码器：Longformer 嵌入 + 投影层
- 消息传递：在用户-查询-模型之间传递信息
- 输出层：预测每个模型的适配分数

---

### 4.4 代理路由器（Agentic Routers）

代理路由器本身就是一个轻量级的 agent，能够自主拆解任务、分配子任务、调用工具并整合结果。

代理路由器的核心特征包括：

- **无内置模型**：只有决策逻辑和模型路由表
- **任务拆解能力**：可以将复杂请求分解为多个子任务
- **工具调用**：支持调用外部工具/API
- **结果聚合**：能够综合多个子任务的结果

---

## 5. 训练方法

### 5.1 训练数据格式

所有路由器的训练数据共享统一格式，核心概念是：**对每个查询，记录每个候选模型的表现**。

训练数据 CSV 的关键列：

- `query`：查询文本
- `model_name`：被调用的模型名称
- `performance`：模型在该查询上的表现分数 (0.0-1.0)
- `embedding_id`：查询嵌入向量的索引
- `task_name`：查询来源的数据集名称
- `ground_truth`：标准答案

### 5.2 训练数据提取

大多数路由器在初始化时从训练数据中提取"最优模型"作为标签：

```python
# 对每个查询，选择 performance 最高的模型
routing_best = routing_data_train.loc[
    routing_data_train.groupby("query")["performance"].idxmax()
]

# 提取最优模型名 → 作为标签
labels = routing_best["model_name"].tolist()

# 提取查询嵌入 → 作为特征
features = [query_embedding_data[i] for i in routing_best["embedding_id"]]
```

### 5.3 各类路由器的训练范式

| 路由器         | 训练范式        | 优化目标                    | 训练复杂度                   |
| ----------- | ----------- | ----------------------- | ----------------------- |
| KNN         | 惰性学习（无显式训练） | N/A                     | O(1)                    |
| SVM         | 最大间隔分类      | Hinge Loss              | O(n²) ~ O(n³)           |
| MLP         | 小批量梯度下降     | Cross-Entropy Loss      | O(n_epochs × n)         |
| MF          | 小批量梯度下降     | Pairwise Ranking Loss   | O(n_epochs × n_pairs)   |
| Elo         | 逻辑回归 MLE    | Binary Log Loss         | O(m³) （m=模型数）           |
| GraphRouter | GNN 端到端训练   | Cross-Entropy on Edges  | O(n_epochs × n × m)     |
| DC          | 对比学习        | Triple Contrastive Loss | O(n_epochs × n)         |
| AutoMix     | 参数搜索        | Max IBC Lift            | O(n_params × n)         |
| HybridLLM   | MLP 回归      | MSE Loss                | O(n_epochs × n)         |
| CausalLM    | Fine-tuning | Cross-Entropy Loss      | O(n_epochs × n)         |
| RouterR1    | 强化学习（RL）    | Reward = Quality − Cost | O(n_episodes × n_steps) |

### 5.4 模型持久化

LLMRouter 支持多种模型保存格式：

- **PyTorch checkpoint** (`.pt`)：用于神经网络路由器（MLP、MF、GNN、DC 等）
- **Pickle** (`.pkl`)：用于 sklearn 路由器（KNN、SVM、Elo 分数等）
- **Transformers 格式**：用于 BERT 类路由器（CausalLM、DC）

保存和加载通过统一的 `save_model()` / `load_model()` 工具函数，自动根据文件路径和对象类型选择适当的序列化方法。

---

## 6. 推理流程

### 6.1 标准推理流程

LLMRouter 的完整推理流程包含四个步骤：

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Step 1: 路由  │───▶│ Step 2: 格式化│───▶│ Step 3: API  │───▶│ Step 4: 评估  │
│ 选择最优模型  │    │ 应用任务Prompt│    │ 调用模型API  │    │ 计算性能指标  │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

**Step 1 — 路由决策**：

```python
# 查询嵌入
emb = get_longformer_embedding(query_text)

# 路由器推理
result = router.route_single({"query": query_text})
selected_model = result["model_name"]
```

**Step 2 — Prompt 格式化**：

```python
# 根据任务类型应用对应的 system/user prompt
formatted = generate_task_query(task_name, {"query": query_text})
# → {"system": "You are a math expert...", "user": "Question: ..."}
```

**Step 3 — API 调用**：

```python
# 通过 LiteLLM 调用选定的模型
response = call_api({
    "api_endpoint": endpoint_url,
    "query": formatted_query,
    "model_name": selected_model,
    "api_name": api_model_identifier,
    "service": service_provider  # NVIDIA, OpenAI, Anthropic 等
})
```

**Step 4 — 性能评估**（如有 ground truth）：

```python
score = calculate_task_performance(
    prediction=response,
    ground_truth=ground_truth,
    task_name=task_name,
    metric=metric_type
)
```

### 6.2 API Key 管理

LLMRouter 支持多种 API Key 配置方式：

1. **服务特定字典格式**（推荐）：
   
   ```bash
   export API_KEYS='{"NVIDIA": "key1,key2", "OpenAI": ["key3"], "Anthropic": "key4"}'
   ```

2. **JSON 数组格式**：`'["key1", "key2"]'`

3. **逗号分隔格式**：`'key1,key2,key3'`

4. **单 Key 格式**：`'key1'`

每个服务独立维护轮转计数器，实现自动负载均衡。API 端点可以在模型级别或路由器级别配置，模型级别的配置具有更高优先级。

### 6.3 路由模式

LLMRouter CLI 支持多种推理模式：

```bash
# 单查询推理
llmrouter infer --router knnrouter --config config.yaml --query "What is ML?"

# 仅路由（不调用 LLM API，只返回模型选择结果）
llmrouter infer --router knnrouter --config config.yaml --query "Hello" --route-only

# 批量推理
llmrouter infer --router knnrouter --config config.yaml --input queries.txt --output results.json

# 自定义生成参数
llmrouter infer --router knnrouter --config config.yaml --query "Explain AI" --temp 0.7 --max-tokens 2048 --verbose
```

---

## 7. 评估体系

### 7.1 评估指标

LLMRouter 内置了全面的评估指标系统，通过装饰器注册机制支持自定义指标扩展。

**内置评估指标**：

| 指标名称             | 键名           | 描述             | 适用场景                |
| ---------------- | ------------ | -------------- | ------------------- |
| Exact Match      | `em`         | 文本精确匹配（归一化后）   | 事实问答                |
| EM (多选题)         | `em_mc`      | 多选题精确匹配        | MMLU, CommonsenseQA |
| Contains EM      | `cem`        | 检查参考答案是否包含在预测中 | 开放域问答               |
| Contains EM + F1 | `cemf1`      | CEM 失败时回退到 F1  | 长文本生成               |
| F1 Score         | `f1`         | 词级别的 F1 分数     | QA, 摘要              |
| BERTScore        | `bert_score` | 基于 BERT 的语义相似度 | 翻译, 释义              |
| GSM8K            | `gsm8k`      | 数学推理专用评估       | 数学题                 |
| MATH             | `math`       | LaTeX 感知的数学评估  | 高等数学                |

**评估装饰器系统**：

```python
@evaluation_metric('my_metric')
def my_eval_function(prediction: str, ground_truth: str, **kwargs) -> float:
    # 自定义评估逻辑
    return score

# 注册后即可在数据中使用
```

### 7.2 批量评估

`evaluate_batch()` 函数支持对批量的预测-真值对进行统一评估：

```python
results = evaluate_batch([
    {"prediction": "...", "ground_truth": "...", "metric": "em"},
    {"prediction": "...", "ground_truth": "...", "metric": "f1"}
], default_metric="em")
```

### 7.3 RouterBench — 统一路由评测基准

OpenClaw Router 内置了 RouterBench（`routerbench.py`），提供系统性的路由器性能对比：

1. **多维度指标**：质量、成本、P50/P95/P99 延迟
2. **Pareto 前沿分析**：识别性价比最优的路由策略
3. **统计显著性检验**：配对 t-test、Wilcoxon signed-rank、bootstrap 置信区间
4. **主动学习样本池**：自动筛选低置信度样本用于人工标注

---

## 8. 用户界面

### 8.1 CLI 命令行

统一的 `llmrouter` 命令支持 6 个子命令：

```bash
llmrouter train     # 训练路由器
llmrouter infer     # 运行推理
llmrouter chat      # 启动聊天界面
llmrouter serve     # 启动 API 服务器
llmrouter list-routers  # 列出所有可用路由器（含自定义）
llmrouter version   # 显示版本信息
```

### 8.2 Gradio 聊天界面

基于 Gradio 的网页聊天界面（`router_chat.py`）支持：

- **三种查询模式**：
  
  - `current_only`：仅基于当前查询路由（默认）
  - `full_context`：结合全部聊天历史进行路由
  - `retrieval`：检索 Top-K 相似历史查询作为路由上下文

- **多轮对话**：维护完整的对话历史

- **实时路由可视化**：展示候选模型评分和路由理由

- **自定义 CSS**：精心设计的用户界面

### 8.3 ComfyUI 可视化工作流

ComfyUI 集成提供拖拽式节点界面，支持：

- **数据节点**：选择数据集、选择 LLM 候选、生成数据
- **单轮路由节点**：KNN、SVM、MLP 等
- **多轮/代理路由节点**：复杂任务的专用路由器
- **实时监控**：查询生成、嵌入提取、模型训练和评估进度
- **模块化流水线**：自由组合数据生成 → 路由器训练 → 评估

---

## 9. 生产部署

### 9.1 OpenClaw Router — OpenAI 兼容 API 服务器

OpenClaw Router 将 LLMRouter 的智能路由能力封装为兼容 OpenAI API 的生产级服务器。

**架构**：

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│  Slack/Discord  │────▶│   OpenClaw Gateway   │────▶│   OpenClaw Router    │
│  (移动端/Web)    │     │   (Socket Mode)      │     │   (Port 8000)       │
└─────────────────┘     └──────────────────────┘     └──────────┬──────────┘
                                                                 │
                        ┌────────────────────────────────────────┼────────────────────────────────────────┐
                        │                                        │                                        │
                        ▼                                        ▼                                        ▼
              ┌─────────────────┐                      ┌─────────────────┐                      ┌─────────────────┐
              │   Fast Model    │                      │ Balanced Model  │                      │ Powerful Model  │
              │   (e.g. 8B)     │                      │   (e.g. 70B)    │                      │  (e.g. 405B)    │
              └─────────────────┘                      └─────────────────┘                      └─────────────────┘
```

**核心特性**：

| 特性                | 描述                                           |
| ----------------- | -------------------------------------------- |
| **OpenAI 兼容 API** | `/v1/chat/completions` 端点，可无缝替换 OpenAI 客户端   |
| **全部路由策略**        | 支持 16+ 种 LLMRouter 路由策略                      |
| **流式响应**          | 完整的 SSE (Server-Sent Events) 流式输出            |
| **WebSocket**     | `/v1/chat/ws` 端点支持全双工通信                      |
| **多模态理解**         | 图像 → VLM 描述 → 文本路由；音频 → Whisper 转录 → 文本路由    |
| **路由记忆**          | 持久化查询→模型映射历史，检索相似历史进行更好的决策                   |
| **模型前缀**          | 可选的 `[model_name]` 前缀标注，方便调试                 |
| **多供应商**          | 支持 Together AI、NVIDIA、OpenAI、Anthropic 和本地模型 |
| **A/B 对比**        | `/v1/chat/compare` 端点同时调用多个模型进行对比            |

**内置路由策略**（服务层）：

- `llmrouter`：使用 ML 路由器（如 KNN、MLP、GraphRouter）
- `random`：随机选择
- `round_robin`：轮询选择
- `rules`：基于规则的匹配（如按查询长度、关键词）
- `llm`：使用 LLM 本身进行路由决策
- `constrained_multi_objective`：约束多目标 Pareto 最优路由
- `finance_risk_adaptive`：金融风险自适应路由
- `contextual_bandit`：情境赌博机在线学习路由
- `cascading_bandit_pareto`：级联 Bandit + Pareto 路由
- `latency_sla_pareto`：延迟 SLA 保证路由

### 9.3 高级路由策略详解

#### 9.3.1 约束多目标 Pareto 路由

该策略通过 Pareto 支配分析在多个冲突目标之间找到最优权衡：

**Pareto 支配定义**：

```
dominates(A, B) 当且仅当:
  A.Q >= B.Q 且 A.R >= B.R 且 A.C <= B.C 且 A.L <= B.L
  且 (A.Q > B.Q 或 A.R > B.R 或 A.C < B.C 或 A.L < B.L)
```

其中 Q=质量, R=可靠性, C=成本, L=延迟。

**效用函数**：

```
Utility = 0.45 × Q + 0.20 × (1−C) + 0.15 × (1−L) + 0.20 × R
```

**算法流程**：

1. 分析任务类型、复杂度和风险等级
2. 设置约束（min_quality, max_cost, max_latency, min_reliability）
3. 过滤满足约束的可行模型
4. 计算 Pareto 前沿（不被任何其他模型支配的模型集合）
5. 从 Pareto 前沿中选择效用最高的模型

#### 9.3.2 金融风险自适应路由

针对金融领域查询的特殊优化，使用非线性效用函数：

```
U = Q^α × R^β × exp(−γ × C) × exp(−δ × L)
```

参数根据风险等级动态调整：

| 风险等级 | α (质量) | β (可靠性) | γ (成本) | δ (延迟) |
| ---- | ------ | ------- | ------ | ------ |
| 高风险  | 2.15   | 1.90    | 0.42   | 0.34   |
| 中风险  | 1.60   | 1.40    | 0.65   | 0.55   |
| 低风险  | 1.20   | 1.05    | 0.95   | 0.88   |

高风险场景下质量和可靠性的指数远高于成本和延迟，确保关键金融决策不会因节省成本而出错。

#### 9.3.3 情境赌博机在线路由

通过在线学习持续优化路由决策：

```
BanditScore = 0.62 × reward + 0.25 × prior + 0.13 × success_rate + exploration
exploration = 0.18 / sqrt(count + 1)
```

其中：

- `reward`：实际路由结果的奖励
- `prior`：多目标效用的先验估计
- `success_rate`：历史成功率
- `exploration`：探索项（随使用次数增加而衰减）

情境键：`{task_type}|{risk_bucket}|{complexity_bucket}`，赌博机状态持久化到 `run_logs/contextual_bandit_state.json`。

#### 9.3.4 级联 Bandit Pareto 路由

结合非线性效用、赌博机历史和时间偏好：

- 从 Pareto 池中选择最便宜的可行候选
- 当置信度低且风险高时，触发级联升级链（escalation_chain）
- 返回后备模型列表以支持自动降级

#### 9.3.5 延迟 SLA Pareto 路由

针对延迟敏感场景：

- 基于风险/复杂度设置延迟 SLA（最大延迟、成本上限、质量下限）
- 过滤满足 SLA 的可行模型
- 组合分数：`0.42 × nonlinear_utility + 0.24 × (1−L) + 0.18 × (1−C) + 0.16 × R`
- 延迟权重 (0.24) 高于标准多目标路由 (0.15)，反映 SLA 场景的特殊需求

### 9.4 路由记忆与多媒体支持

**路由记忆**（`memory.py`）：

- 使用 Contriever（`facebook/contriever-msmarco`）对历史查询进行稠密检索
- 持久化查询→模型映射历史到 JSONL 文件
- 新查询时检索 Top-K 相似历史，辅助路由决策

**多媒体理解**（`media.py`）：

- 图像：使用 VLM（如 Qwen3-VL-8B）生成文本描述 → 送入路由
- 音频：使用 Whisper 转录 → 送入路由
- 视频：提取关键帧 → VLM 描述 → 路由

**配置示例**：

```yaml
serve:
  host: "0.0.0.0"
  port: 8000
  show_model_prefix: true

router:
  strategy: llmrouter
  algorithm: graphrouter

memory:
  enabled: true
  path: "~/.llmrouter/openclaw_memory.jsonl"
  top_k: 10
  retriever_model: "facebook/contriever-msmarco"

media:
  enabled: true
  vision_model: "Qwen/Qwen3-VL-8B-Instruct"
  audio_model: "openai/whisper-large-v3"
```

### 9.2 前端管理面板

OpenClaw Router 附带一个功能完整的单页 Web 应用（`frontend/`），支持：

- **智能对话**：通过路由器自动选择最佳模型
- **路由中心**：可视化服务层和算法层的运行配置
- **模型管理**：CRUD 操作管理接入的模型和供应商
- **实验验证**：运行路由实验、查看模拟和真实调用结果
- **可视化分析**：Pareto 图、雷达图、任务类型对比柱状图、综合效用排名图
- **运行日志**：查看每次路由选择、模型调用和自动降级过程
- **系统状态**：监控服务健康状态和 API 接口

---

## 10. 实验与分析

### 10.1 实验设计

LLMRouter 内置了完整的实验框架（通过前端面板和 OpenClaw Router），支持：

1. **任务集**：从 14 个代表性任务中选择

2. **策略对比**：
   
   - 基线：固定小模型、固定大模型
   - 服务层：随机、轮询、规则匹配
   - 算法层：KNN、SVM、MLP、MF、Elo、GraphRouter 等
   - 调度优化：保守串行、平衡依赖图、极速并行

3. **多目标评估**：质量（Quality）、成本（Cost）、延迟（Latency）、可靠性（Reliability）

4. **效用函数**：
   
   ```
   Utility = w_q × Quality + w_c × (1 − Cost) + w_l × (1 − Latency) + w_r × Reliability
   ```
   
   其中权重可配置，默认等权重

5. **统计检验**：
   
   - Paired t-test
   - Wilcoxon signed-rank test
   - Bootstrap 置信区间（N=10000）

### 10.2 RouterBench 评估维度

RouterBench 提供标准化的多维度评估：

```
┌──────────────────────────────────────────────────────┐
│                  RouterBench 评估矩阵                   │
├────────────┬─────────┬─────────┬─────────┬──────────┤
│  策略       │  质量↑  │  成本↓  │ P50延迟↓ │ 可靠性↑  │
├────────────┼─────────┼─────────┼─────────┼──────────┤
│ 固定小模型  │  0.72   │  0.15   │  1.2s   │  0.95    │
│ 固定大模型  │  0.89   │  0.90   │  5.8s   │  0.98    │
│ Random     │  0.80   │  0.52   │  3.5s   │  0.96    │
│ KNN路由    │  0.84   │  0.38   │  2.8s   │  0.97    │
│ MLP路由    │  0.85   │  0.35   │  2.6s   │  0.97    │
│ GraphRouter│  0.87   │  0.42   │  3.1s   │  0.97    │
│ Pareto最优 │  0.87   │  0.33   │  2.4s   │  0.98    │
└────────────┴─────────┴─────────┴─────────┴──────────┘
```

### 10.3 统计显著性检验

RouterBench 使用三种统计检验方法确保对比结果的可靠性：

**1. Bootstrap 置信区间**（N=600 次重采样，种子=20260702）：

```
对于每对策略，在逐任务差异上重采样 600 次，
计算每个重采样的均值，取 2.5th 和 97.5th 百分位数形成 95% CI。
若 CI 不包含零，则差异在 α=0.05 水平上统计显著。
```

**2. 配对 t 检验（Paired t-test）**：

```
t = mean(D) / (std(D) / sqrt(n))
p = 2 × (1 − Φ(|t|))
```

其中 D = {score_strategy_A(i) − score_strategy_B(i)} 为逐任务差异向量，Φ 为标准正态 CDF。

**3. Wilcoxon 符号秩检验（Wilcoxon Signed-Rank Test）**：

```
对非零差异 |D_i| 排秩 R_i，
W⁺ = sum(R_i · 1[D_i > 0])
W⁻ = sum(R_i · 1[D_i < 0])
W = min(W⁺, W⁻)
z = (W − n(n+1)/4) / sqrt(n(n+1)(2n+1)/24)
```

这是对配对 t 检验的非参数补充，不依赖正态性假设。

**4. 主动学习样本池**：
自动筛选以下三类样本供人工标注：

- 高不确定性：路由置信度 ≥ 0.65
- 低分差：候选模型间分数差距 ≤ 0.04
- 低效用：路由效用分数 ≤ 0.45

这些样本代表路由器最不确定或表现最差的场景，对其进行人工标注可以有效降低标注成本同时最大化模型改进。

### 10.4 路由开销分析

路由器的推理开销（Router Overhead）是评估其实际价值的关键指标：

| 路由器         | 平均推理时间      | 参数数量       | 内存占用        |
| ----------- | ----------- | ---------- | ----------- |
| KNN         | 5-15 ms     | N/A        | O(n·d) 训练数据 |
| SVM         | 2-8 ms      | O(d·c)     | 小           |
| MLP         | 1-3 ms      | ~100K-500K | 小           |
| MF          | 1-2 ms      | ~50K-200K  | 极小          |
| Elo         | <1 ms       | O(c)       | 极小          |
| GraphRouter | 10-50 ms    | ~1M-5M     | 中           |
| DC          | 20-80 ms    | ~100M+     | 大           |
| CausalLM    | 50-200 ms   | ~100M+     | 大           |
| RouterR1    | 500-5000 ms | ~7B+       | 极大 (GPU)    |

路由器开销占总延迟的比例通常控制在 1-5% 以内（对于推理延迟 1-10s 的模型），除 RouterR1 外均可忽略不计。

### 10.4 Game Theory Pareto 分析

LLMRouter 的 Pareto 前沿分析揭示了路由策略在成本-质量空间中的最优边界：

```
Quality
  1.0 │
      │                    ● LargeLLM
 0.90 │              ● GraphRouter
      │         ● MLP      ● MF
 0.85 │    ● KNN
      │       ● Random
 0.80 │
      │           ● SmallLLM
 0.70 │
      └──────────────────────────────▶ Cost
       0.0   0.2   0.4   0.6   0.8   1.0
```

Pareto 前沿上的策略（GraphRouter 等）代表无法在不降低质量的前提下进一步降低成本，或在无法不增加成本的前提下进一步提高质量——它们是"性价比前沿"上的最优解。

---

## 11. 自定义扩展

### 11.1 自定义路由器

用户只需继承 `MetaRouter` 并实现 `route_single` 和 `route_batch` 方法即可创建自定义路由器：

```python
from llmrouter.models.meta_router import MetaRouter
import torch.nn as nn

class MyRouter(MetaRouter):
    def __init__(self, yaml_path: str):
        super().__init__(model=nn.Identity(), yaml_path=yaml_path)
        self.llm_names = list(self.llm_data.keys())

    def route_single(self, query_input: dict) -> dict:
        query = query_input['query']
        # 自定义路由逻辑
        selected = self.llm_names[0] if len(query) < 50 else self.llm_names[-1]
        return {"query": query, "model_name": selected, "predicted_llm": selected}

    def route_batch(self, batch: list) -> list:
        return [self.route_single(q) for q in batch]
```

路由器放置于 `custom_routers/` 目录下后，会被插件系统自动发现和注册，使用方式与内置路由器完全一致。

### 11.2 自定义任务

用户可以通过装饰器系统添加自定义任务类型和评估指标：

```python
from llmrouter.utils.prompting import register_prompt
from llmrouter.evaluation import evaluation_metric

@register_prompt('my_task', default_metric='my_metric')
def format_my_task_prompt(sample_data):
    return {
        "system": "You are an expert at ...",
        "user": f"Question: {sample_data.get('query', '')}"
    }

@evaluation_metric('my_metric')
def my_eval(prediction: str, ground_truth: str, **kwargs) -> float:
    return 1.0 if prediction == ground_truth else 0.0
```

---

## 12. 相关工作

### 12.1 路由方法

| 方法                 | 核心思想          | 发表会议         | LLMRouter 实现       |
| ------------------ | ------------- | ------------ | ------------------ |
| RouteLLM           | 偏好数据驱动的路由学习   | ICLR 2025    | MFRouter           |
| RouterDC           | 双对比学习查询-LLM对齐 | NeurIPS 2024 | DCRouter           |
| AutoMix            | 自动混合大小模型      | NeurIPS 2024 | AutoMix            |
| Hybrid LLM         | 成本效率质量感知路由    | ICLR 2024    | HybridLLM          |
| GraphRouter        | 图神经网络路由选择     | ICLR 2025    | GraphRouter        |
| GMTRouter          | 个性化多轮路由       | arXiv 2511   | GMTRouter          |
| PersonalizedRouter | GNN用户偏好建模     | arXiv 2511   | PersonalizedRouter |
| Router-R1          | 强化学习多轮路由      | NeurIPS 2025 | RouterR1           |

### 12.2 与其他 LLM 路由框架的对比

| 特性             | LLMRouter | OpenRouter | Martian | Portkey |
| -------------- | --------- | ---------- | ------- | ------- |
| 路由器数量          | 16+       | ~5         | ~3      | ~4      |
| 自定义路由器         | ✅ 插件化     | ❌          | ❌       | 部分      |
| 本地部署           | ✅         | ❌          | ❌       | ❌       |
| 开源             | ✅ MIT     | ❌          | ❌       | 部分      |
| 数据生成管线         | ✅ 完整      | ❌          | ❌       | ❌       |
| GNN/对比学习       | ✅         | ❌          | ❌       | ❌       |
| 个性化路由          | ✅         | ❌          | ❌       | ❌       |
| 多轮代理路由         | ✅         | ❌          | 部分      | ❌       |
| ComfyUI 集成     | ✅         | ❌          | ❌       | ❌       |
| RouterBench 评测 | ✅         | ❌          | ❌       | ❌       |

---

## 13. 讨论

### 13.1 框架的优势

1. **最全面的路由器集合**：LLMRouter 是目前开源社区中覆盖路由策略最广的框架
2. **研究可复现性**：每个路由器都标注了相应论文来源，便于学术追踪和复现
3. **统一接口**：所有路由器共享相同的训练、推理和评估接口，降��了对比实验的成本
4. **从研究到生产的桥梁**：同一套代码可以用于学术实验和生产部署
5. **活跃的社区**：1000+ GitHub Stars，活跃的 Slack/微信社区，持续的版本迭代

### 13.2 当前局限

1. **代码重复**：`route_batch()` 方法中的 API 调用和评估逻辑在多个路由器中重复，增加了维护成本
2. **嵌入方式单一**：当前仅支持 Longformer 嵌入，不支持 E5、BGE、OpenAI Embeddings 等替代方案
3. **缺少在线学习**：路由器训练后静态部署，无法从实际使用反馈中持续学习
4. **冷启动问题**：对新任务、新用户、新模型缺乏智能的默认路由策略
5. **测试覆盖不足**：缺乏自动化的单元测试和持续集成
6. **多模态路由器缺失**：数据管线支持多模态，但尚无专门针对多模态任务优化的路由器

### 13.3 未来方向

1. **Pipeline 抽象重构**：将路由决策、API 调用和评估解耦为可组合的 Pipeline 阶段
2. **嵌入模型可替换**：支持多种嵌入模型的热插拔
3. **在线反馈学习**：支持从用户反馈（👍/👎）中持续优化路由器
4. **多模态路由器**：为图像/视频/音频查询设计专用的路由策略
5. **路由器集成**：支持多个路由器的投票/加权集成，提升鲁棒性
6. **语义路由器**：基于 LLM 的任务类型理解进行路由，而非仅依赖嵌入相似度
7. **强化学习训练**：将 RouterR1 的 RL 训练方法推广到更多路由器
8. **分布式路由**：支持跨多个 API 供应商的智能负载分配和故障转移

---

## 14. 结论

本文系统性地介绍了 LLMRouter——一个面向大语言模型智能路由的统一开源框架。LLMRouter 通过统一的架构抽象（MetaRouter 和 BaseTrainer）、完整的数据管线、16+ 种路由策略、插件化扩展机制以及生产级部署支持，为 LLM 路由的研究和应用提供了全面的基础设施。

该框架不仅降低了不同路由方法之间的对比门槛，也为研究者快速验证新的路由想法提供了便利。通过将前沿学术成果（RouteLLM、RouterDC、AutoMix、GraphRouter、Router-R1 等）整合到统一框架中，LLMRouter 正在成为 LLM 路由领域的标准化工具。

随着 LLM 生态的持续扩展和路由技术的不断演进，LLMRouter 的开放式架构使其能够持续吸收社区的最新研究成果，推动 LLM 路由从"选最好的模型"走向"为每个请求智能选择最合适的模型"。

---

## 参考文献

1. Ong, I., et al. "RouteLLM: Learning to Route LLMs with Preference Data." ICLR 2025.
2. Chen, S., et al. "RouterDC: Query-Based Router by Dual Contrastive Learning." NeurIPS 2024.
3. Aggarwal, P., et al. "AutoMix: Automatically Mixing Language Models." NeurIPS 2024.
4. Ding, D., et al. "Hybrid LLM: Cost-Efficient and Quality-Aware Query Routing." ICLR 2024.
5. Feng, T., et al. "GraphRouter: A Graph-based Router for LLM Selections." ICLR 2025.
6. Feng, T., et al. "GMTRouter: Personalized LLM Router over Multi-turn User Interactions." arXiv:2511.08590, 2025.
7. Zhang, H., et al. "PersonalizedRouter: Personalized LLM Routing via Graph-based User Preference Modeling." arXiv:2511.16883, 2025.
8. Lei, Z., et al. "Router-R1: Teaching LLMs Multi-Round Routing and Aggregation via RL." NeurIPS 2025.
9. Feng, T., et al. "LLMRouter: An Open-Source Library for LLM Routing." GitHub Repository, 2025.
10. Feng, T., et al. "RouteProfile: A General Framework for Designing LLM Routing Profiles." arXiv:2605.00180, 2026.
