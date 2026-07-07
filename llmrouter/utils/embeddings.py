"""
Embedding utilities for LLMRouter scripts (Longformer version)
"""

import os
import hashlib
import torch
from transformers import AutoModel, AutoTokenizer


# Model config
_MODEL_NAME: str = "allenai/longformer-base-4096"

# Lazy-loaded globals
_tokenizer = None
_model = None
_device = None


def _get_device() -> torch.device:
    """
    Select device for embedding model.

    Override with env var `LLMROUTER_EMBEDDING_DEVICE` (e.g. "cpu", "cuda", "cuda:0").
    """
    global _device
    if _device is not None:
        return _device

    device_override = (os.environ.get("LLMROUTER_EMBEDDING_DEVICE") or "").strip()
    if device_override:
        _device = torch.device(device_override)
        return _device

    if torch.cuda.is_available():
        _device = torch.device("cuda")
    elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        _device = torch.device("mps")
    else:
        _device = torch.device("cpu")
    return _device


def _init_model():
    """Initialize tokenizer/model on first use."""
    global _tokenizer, _model
    if _tokenizer is not None and _model is not None:
        return

    if os.environ.get("LLMROUTER_OFFLINE_EMBEDDINGS") == "1":
        _tokenizer = False
        _model = False
        return

    device = _get_device()
    try:
        _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
        _model = AutoModel.from_pretrained(_MODEL_NAME).to(device)
        _model.eval()
    except Exception as error:
        if os.environ.get("LLMROUTER_STRICT_EMBEDDINGS") == "1":
            raise
        print(f"[Embedding] Warning: Longformer unavailable, using offline hash embeddings: {error}")
        _tokenizer = False
        _model = False


def _hash_embedding(text: str, dim: int = 768) -> torch.Tensor:
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).digest()
    values = []
    counter = 0
    while len(values) < dim:
        block = hashlib.sha256(digest + counter.to_bytes(4, "little")).digest()
        values.extend((byte / 127.5) - 1.0 for byte in block)
        counter += 1
    return torch.tensor(values[:dim], dtype=torch.float32)


def get_longformer_embedding(texts):
    """
    Get Longformer embeddings for given texts.

    Args:
        texts (str or list[str]): Input text(s) to encode.

    Returns:
        torch.Tensor or list[torch.Tensor]:
            - Single embedding (torch.Tensor) if only one input text.
            - Batch embeddings (torch.Tensor) if multiple input texts.
    """
    _init_model()

    # -------------------------
    # 2. Input handling
    # -------------------------
    single_input = isinstance(texts, str)
    if isinstance(texts, str):
        texts = [texts]

    if _tokenizer is False or _model is False:
        embeddings = torch.stack([_hash_embedding(text) for text in texts]).cpu()
        if single_input:
            return embeddings[0]
        return embeddings

    # -------------------------
    # 3. Tokenization
    # -------------------------
    device = _get_device()
    inputs = _tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=4096,
        return_tensors="pt",
    ).to(device)

    # -------------------------
    # 4. Model forward pass
    # -------------------------
    with torch.no_grad():
        outputs = _model(**inputs)
        last_hidden_state: torch.Tensor = outputs.last_hidden_state  # (batch, seq_len, hidden_dim)

    # -------------------------
    # 5. Mean pooling
    # -------------------------
    attention_mask: torch.Tensor = inputs["attention_mask"]
    mask_expanded: torch.Tensor = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    sentence_embeddings: torch.Tensor = (last_hidden_state * mask_expanded).sum(1) / mask_expanded.sum(1)

    # -------------------------
    # 6. Return result (move to CPU for safety)
    # -------------------------
    sentence_embeddings = sentence_embeddings.cpu()

    if len(texts) == 1:
        return sentence_embeddings[0]
    return sentence_embeddings


def parallel_embedding_task(data):
    """
    Parallel task for generating Longformer embeddings.

    Args:
        data (tuple): (id, query_text)

    Returns:
        tuple: (id, query_embedding, success_flag)
    """
    success: bool = True
    id, query_t = data
    query_t_embedding = None

    try:
        # Compute embedding
        query_t_embedding = get_longformer_embedding(query_t)
    except Exception as e:
        print(f"Error in parallel embedding task (id={id}): {e}")
        success = False
        query_t_embedding = None

    return id, query_t_embedding, success
