from typing import Any, Dict, List, Optional
import copy
import os

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from llmrouter.models.meta_router import MetaRouter
from llmrouter.utils import (
    calculate_task_performance,
    call_api,
    generate_task_query,
    get_longformer_embedding,
    load_model,
)


class MLPClassifierNN(nn.Module):
    def __init__(self, input_dim: int, hidden_layer_sizes: List[int], num_classes: int, activation: str = "relu"):
        super().__init__()
        self.activation_name = activation
        dimensions = [input_dim, *hidden_layer_sizes, num_classes]
        self.layers = nn.ModuleList(
            nn.Linear(dimensions[index], dimensions[index + 1])
            for index in range(len(dimensions) - 1)
        )

    @property
    def device(self):
        return next(self.parameters()).device

    def _activation(self, value):
        return {
            "relu": F.relu,
            "tanh": torch.tanh,
            "logistic": torch.sigmoid,
            "identity": lambda item: item,
        }.get(self.activation_name, F.relu)(value)

    def forward(self, value):
        for layer in self.layers[:-1]:
            value = self._activation(layer(value))
        return self.layers[-1](value)

    def predict(self, value):
        self.eval()
        with torch.no_grad():
            return torch.argmax(self(value), dim=-1)


class MLPRouter(MetaRouter):
    """MLP router supporting legacy hard labels and structured soft-label checkpoints."""

    def __init__(self, yaml_path: str):
        super().__init__(model=nn.Identity(), yaml_path=yaml_path)
        self.hparam = self.cfg["hparam"]
        best = self._best_routes(self.routing_data_train)
        self.model_names = best["model_name"].unique().tolist()
        self.model_to_idx = {name: index for index, name in enumerate(self.model_names)}
        self.idx_to_model = {index: name for name, index in self.model_to_idx.items()}
        self.task_names = sorted(self.routing_data_train["task_name"].dropna().unique().tolist())
        self.task_to_idx = {name: index for index, name in enumerate(self.task_names)}
        self.num_classes = len(self.model_names)
        self.embedding_dim = int(next(iter(self.query_embedding_data.values())).numel())
        self.input_dim = self.embedding_dim

        ids = best["embedding_id"].astype(int).tolist()
        self.query_embedding_list = torch.stack([self.query_embedding_data[index] for index in ids]).float()
        self.model_name_list = best["model_name"].tolist()
        self.label_indices = torch.tensor(
            [self.model_to_idx[name] for name in self.model_name_list], dtype=torch.long
        )
        self.mlp_model = MLPClassifierNN(
            self.input_dim,
            self.hparam.get("hidden_layer_sizes", [128, 64]),
            self.num_classes,
            self.hparam.get("activation", "relu"),
        )
        self.checkpoint_metadata = None

    @staticmethod
    def _best_routes(frame):
        return frame.loc[frame.groupby("query")["performance"].idxmax()].reset_index(drop=True)

    def _model_path(self):
        configured = self.cfg["model_path"].get("load_model_path") or self.cfg["model_path"].get("save_model_path")
        if not configured:
            raise ValueError("model_path must define load_model_path or save_model_path")
        package_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return os.path.join(package_root, configured)

    def _load_mlp_model(self, device: str = "cpu"):
        payload = load_model(self.load_model_path)
        if isinstance(payload, dict) and payload.get("format_version") == 2:
            self.checkpoint_metadata = payload
            self.model_names = payload["model_names"]
            self.model_to_idx = {name: index for index, name in enumerate(self.model_names)}
            self.idx_to_model = {index: name for index, name in enumerate(self.model_names)}
            self.task_names = payload["task_names"]
            self.task_to_idx = {name: index for index, name in enumerate(self.task_names)}
            model = MLPClassifierNN(
                payload["input_dim"], payload["hidden_layer_sizes"], len(self.model_names), payload["activation"]
            )
            model.load_state_dict(payload["state_dict"])
            model.to(device).eval()
            return model, "soft_pytorch"
        if isinstance(payload, dict) and any(key.startswith("layers") for key in payload):
            model = MLPClassifierNN(
                self.input_dim,
                self.hparam.get("hidden_layer_sizes", [128, 64]),
                self.num_classes,
                self.hparam.get("activation", "relu"),
            )
            model.load_state_dict(payload)
            model.to(device).eval()
            return model, "pytorch"
        return payload, "sklearn"

    def _structured_feature(self, embedding: torch.Tensor, task_name: Optional[str]):
        metadata = self.checkpoint_metadata
        mean = torch.tensor(metadata["embedding_mean"], dtype=torch.float32)
        std = torch.tensor(metadata["embedding_std"], dtype=torch.float32)
        normalized = (embedding.float().cpu() - mean) / std
        task = torch.zeros(len(self.task_names), dtype=torch.float32)
        if task_name in self.task_to_idx:
            task[self.task_to_idx[task_name]] = 1.0
        return torch.cat([normalized, task])

    def _select_model(self, model, model_type, embedding, task_name):
        if model_type == "soft_pytorch":
            feature = self._structured_feature(embedding, task_name).unsqueeze(0).to(model.device)
            with torch.no_grad():
                probabilities = torch.softmax(model(feature), dim=1).squeeze(0).cpu().numpy()
            costs = np.asarray(self.checkpoint_metadata["normalized_costs"], dtype=np.float32)
            cost_lambda = float(self.cfg.get("routing", {}).get("cost_lambda", 0.0))
            utilities = probabilities - cost_lambda * costs
            selected = int(np.argmax(utilities))
            return self.model_names[selected], probabilities, costs, utilities
        if model_type == "pytorch":
            selected = int(model.predict(embedding.unsqueeze(0).to(model.device)).item())
            return self.idx_to_model[selected], None, None, None
        return model.predict([embedding.numpy()])[0], None, None, None

    def route_single(self, query: Dict[str, Any]) -> Dict[str, Any]:
        self.load_model_path = self._model_path()
        model, model_type = self._load_mlp_model()
        embedding = get_longformer_embedding(query["query"])
        selected, scores, costs, utilities = self._select_model(model, model_type, embedding, query.get("task_name"))
        output = copy.copy(query)
        output["model_name"] = selected
        if scores is not None:
            output["predicted_performance_distribution"] = dict(zip(self.model_names, scores.tolist()))
            output["normalized_costs"] = dict(zip(self.model_names, costs.tolist()))
            output["utilities"] = dict(zip(self.model_names, utilities.tolist()))
        return output

    def route_batch(self, batch: Optional[Any] = None, task_name: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = batch if isinstance(batch, list) else ([batch] if batch is not None else self.query_data_test or [])
        outputs = []
        for row in rows:
            row_copy = copy.copy(row) if isinstance(row, dict) else {"query": str(row)}
            row_task = row_copy.get("task_name", task_name)
            routed = self.route_single({"query": row_copy.get("query", ""), "task_name": row_task})
            model_name = routed["model_name"]
            row_copy.update({key: value for key, value in routed.items() if key != "query"})
            formatted = None
            if row_task:
                try:
                    formatted = generate_task_query(row_task, {"query": row_copy["query"], "choices": row_copy.get("choices")})
                except (ValueError, KeyError) as error:
                    print(f"Warning: Failed to format query with task '{row_task}': {error}. Using original query.")
            query_text = formatted["user"] if formatted else row_copy["query"]
            system_prompt = formatted["system"] if formatted else None
            if formatted:
                row_copy["formatted_query"] = formatted
            info = self.llm_data.get(model_name, {}) if self.llm_data else {}
            endpoint = info.get("api_endpoint", self.cfg.get("api_endpoint"))
            if not endpoint:
                raise ValueError(f"API endpoint not found for model '{model_name}'")
            request = {
                "api_endpoint": endpoint, "query": query_text, "system_prompt": system_prompt,
                "model_name": model_name, "api_name": info.get("model", model_name),
            }
            if info.get("service"):
                request["service"] = info["service"]
            result = call_api(request, max_tokens=1024, temperature=0.7)
            row_copy.update({
                "response": result.get("response", ""),
                "prompt_tokens": result.get("prompt_tokens", 0),
                "completion_tokens": result.get("completion_tokens", 0),
                "input_token": result.get("prompt_tokens", 0),
                "output_token": result.get("completion_tokens", 0),
                "success": "error" not in result,
            })
            ground_truth = row_copy.get("ground_truth") or row_copy.get("gt") or row_copy.get("answer")
            if ground_truth:
                performance = calculate_task_performance(
                    row_copy["response"], ground_truth, task_name=row_task, metric=row_copy.get("metric")
                )
                if performance is not None:
                    row_copy["task_performance"] = performance
            outputs.append(row_copy)
        return outputs
