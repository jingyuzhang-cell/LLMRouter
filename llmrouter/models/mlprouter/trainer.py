import json
import os
import random

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import f1_score
from torch.utils.data import DataLoader, TensorDataset

from llmrouter.models.base_trainer import BaseTrainer
from llmrouter.utils import load_model, save_model
from .router import MLPClassifierNN


class MLPTrainer(BaseTrainer):
    """Train a structured MLP against the full per-model performance distribution."""

    def __init__(self, router, optimizer=None, device="cpu"):
        super().__init__(router=router, optimizer=optimizer, device=device)
        self.device = device
        self.router = router
        self.hparam = router.hparam
        self.seed = int(self.hparam.get("seed", 42))
        random.seed(self.seed)
        np.random.seed(self.seed)
        torch.manual_seed(self.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(self.seed)

        package_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        initial = router.cfg["model_path"].get("ini_model_path")
        self.ini_model_path = os.path.join(package_root, initial) if initial else ""
        self.save_model_path = os.path.join(package_root, router.cfg["model_path"]["save_model_path"])
        self.history_path = f"{self.save_model_path}.history.json"
        self.temperature = float(self.hparam.get("soft_label_temperature", 0.1))
        self.soft_blend = float(self.hparam.get("tie_soft_blend", 0.2))
        self.clear_gap_threshold = float(self.hparam.get("clear_gap_threshold", 0.1))
        self.clear_gap_weight = float(self.hparam.get("clear_gap_weight", 3.0))
        self.regret_loss_weight = float(self.hparam.get("regret_loss_weight", 1.0))
        self.epochs = int(self.hparam.get("epochs", 100))
        self.batch_size = int(self.hparam.get("batch_size", 64))
        self.patience = int(self.hparam.get("early_stopping_patience", 15))
        self.min_delta = float(self.hparam.get("early_stopping_min_delta", 1e-4))
        self.hidden_layer_sizes = self.hparam.get("hidden_layer_sizes", [128, 64])
        self.activation = self.hparam.get("activation", "relu")

        raw_train_x, self.train_scores = self._prepare_frame(router.routing_data_train)
        raw_validation_x, self.validation_scores = self._prepare_frame(router.routing_data_validation)
        self.embedding_mean = raw_train_x[:, : router.embedding_dim].mean(dim=0)
        self.embedding_std = raw_train_x[:, : router.embedding_dim].std(dim=0).clamp_min(1e-6)
        self.train_features = self._normalize(raw_train_x)
        self.validation_features = self._normalize(raw_validation_x)
        self.train_targets = self._tie_aware_targets(self.train_scores)
        self.validation_targets = self._tie_aware_targets(self.validation_scores)
        self.train_regrets = self.train_scores.max(dim=1, keepdim=True).values - self.train_scores
        self.validation_regrets = self.validation_scores.max(dim=1, keepdim=True).values - self.validation_scores
        sorted_scores = self.train_scores.sort(dim=1, descending=True).values
        self.train_gaps = sorted_scores[:, 0] - sorted_scores[:, 1]
        self.train_sample_weights = torch.where(
            self.train_gaps > self.clear_gap_threshold,
            torch.full_like(self.train_gaps, self.clear_gap_weight),
            torch.ones_like(self.train_gaps),
        )

        self.model = MLPClassifierNN(
            self.train_features.shape[1], self.hidden_layer_sizes, router.num_classes, self.activation
        ).to(device)
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=float(self.hparam.get("lr", 1e-3)),
            weight_decay=float(self.hparam.get("alpha", 1e-4)),
        )
        self.normalized_costs = self._normalized_costs()
        self.history = []
        self.best_epoch = 0
        self.best_validation_metrics = None
        self.best_validation_score = float("-inf")
        print(
            f"[MLPTrainer] Soft labels on {device}; seed={self.seed}, temperature={self.temperature}, "
            f"train={len(self.train_features)}, validation={len(self.validation_features)}"
        )

    def _prepare_frame(self, frame):
        if frame is None or frame.empty:
            raise ValueError("Soft-label MLP training requires non-empty routing train/validation data")
        pivot = frame.pivot(index="query", columns="model_name", values="performance")
        pivot = pivot.reindex(columns=self.router.model_names)
        if pivot.isna().any().any():
            raise ValueError("Every query must have performance for every configured model")
        metadata = frame.drop_duplicates("query").set_index("query").loc[pivot.index]
        embeddings = torch.stack(
            [self.router.query_embedding_data[int(index)] for index in metadata["embedding_id"]]
        ).float()
        task_features = torch.zeros((len(metadata), len(self.router.task_names)), dtype=torch.float32)
        for row, task in enumerate(metadata["task_name"]):
            if task in self.router.task_to_idx:
                task_features[row, self.router.task_to_idx[task]] = 1.0
        return torch.cat([embeddings, task_features], dim=1), torch.tensor(pivot.to_numpy(), dtype=torch.float32)

    def _normalize(self, features):
        output = features.clone()
        output[:, : self.router.embedding_dim] = (
            output[:, : self.router.embedding_dim] - self.embedding_mean
        ) / self.embedding_std
        return output

    def _normalized_costs(self):
        costs = []
        for name in self.router.model_names:
            info = (self.router.llm_data or {}).get(name, {})
            costs.append((float(info.get("input_price", 0)) + float(info.get("output_price", 0))) / 2)
        values = np.asarray(costs, dtype=np.float32)
        spread = values.max() - values.min()
        return ((values - values.min()) / spread if spread > 0 else np.zeros_like(values)).tolist()

    def _tie_aware_targets(self, scores):
        oracle = scores.max(dim=1, keepdim=True).values
        optimal_mask = torch.isclose(scores, oracle, atol=1e-8).float()
        tie_targets = optimal_mask / optimal_mask.sum(dim=1, keepdim=True)
        soft_targets = torch.softmax(scores / self.temperature, dim=1)
        return (1.0 - self.soft_blend) * tie_targets + self.soft_blend * soft_targets

    def _training_loss(self, logits, targets, regrets, sample_weights):
        cross_entropy = -(targets * torch.log_softmax(logits, dim=1)).sum(dim=1)
        expected_regret = (torch.softmax(logits, dim=1) * regrets).sum(dim=1)
        per_sample = cross_entropy + self.regret_loss_weight * expected_regret
        return (per_sample * sample_weights).sum() / sample_weights.sum()

    def _metrics(self, features, scores):
        self.model.eval()
        with torch.no_grad():
            logits = self.model(features.to(self.device)).cpu()
        predicted = logits.argmax(dim=1).numpy()
        score_values = scores.numpy()
        chosen = score_values[np.arange(len(predicted)), predicted]
        oracle = score_values.max(axis=1)
        arbitrary_truth = score_values.argmax(axis=1)
        optimal = np.isclose(chosen, oracle, atol=1e-8)
        return {
            "optimal_set_accuracy": float(optimal.mean()),
            "mean_regret": float((oracle - chosen).mean()),
            "mean_selected_performance": float(chosen.mean()),
            "macro_f1": float(f1_score(arbitrary_truth, predicted, average="macro", zero_division=0)),
        }

    def _checkpoint(self):
        return {
            "format_version": 2,
            "objective": "soft_performance_distribution",
            "state_dict": {key: value.detach().cpu() for key, value in self.model.state_dict().items()},
            "input_dim": int(self.train_features.shape[1]),
            "embedding_dim": self.router.embedding_dim,
            "hidden_layer_sizes": self.hidden_layer_sizes,
            "activation": self.activation,
            "model_names": self.router.model_names,
            "task_names": self.router.task_names,
            "embedding_mean": self.embedding_mean.tolist(),
            "embedding_std": self.embedding_std.tolist(),
            "soft_label_temperature": self.temperature,
            "tie_soft_blend": self.soft_blend,
            "clear_gap_threshold": self.clear_gap_threshold,
            "clear_gap_weight": self.clear_gap_weight,
            "regret_loss_weight": self.regret_loss_weight,
            "normalized_costs": self.normalized_costs,
            "seed": self.seed,
            "best_epoch": self.best_epoch,
            "best_validation_metrics": self.best_validation_metrics,
        }

    def train(self, dataloader=None):
        if self.ini_model_path and os.path.exists(self.ini_model_path):
            payload = load_model(self.ini_model_path)
            self.model.load_state_dict(payload.get("state_dict", payload))
        if dataloader is None:
            generator = torch.Generator().manual_seed(self.seed)
            dataloader = DataLoader(
                TensorDataset(
                    self.train_features, self.train_targets, self.train_regrets,
                    self.train_sample_weights,
                ),
                batch_size=self.batch_size, shuffle=True, generator=generator,
            )
        os.makedirs(os.path.dirname(self.save_model_path), exist_ok=True)
        stale = 0
        stopped_early = False
        for epoch in range(1, self.epochs + 1):
            self.model.train()
            losses = []
            for features, targets, regrets, sample_weights in dataloader:
                self.optimizer.zero_grad()
                loss = self._training_loss(
                    self.model(features.to(self.device)), targets.to(self.device),
                    regrets.to(self.device), sample_weights.to(self.device),
                )
                loss.backward()
                self.optimizer.step()
                losses.append(loss.item())
            validation = self._metrics(self.validation_features, self.validation_scores)
            monitor = validation["optimal_set_accuracy"] - validation["mean_regret"]
            record = {"epoch": epoch, "loss": float(np.mean(losses)), "monitor": monitor, **validation}
            self.history.append(record)
            if monitor > self.best_validation_score + self.min_delta:
                self.best_epoch = epoch
                self.best_validation_metrics = validation
                self.best_validation_score = monitor
                stale = 0
                save_model(self._checkpoint(), self.save_model_path)
            else:
                stale += 1
            if epoch == 1 or epoch % 5 == 0:
                print(
                    f"[MLPTrainer] Epoch {epoch}/{self.epochs} loss={record['loss']:.4f} "
                    f"optimal={validation['optimal_set_accuracy']:.4f} "
                    f"regret={validation['mean_regret']:.4f} "
                    f"selected={validation['mean_selected_performance']:.4f} "
                    f"macro_f1={validation['macro_f1']:.4f}"
                )
            if stale >= self.patience:
                stopped_early = True
                print(f"[MLPTrainer] Early stopping at epoch {epoch}; best epoch={self.best_epoch}")
                break
        payload = load_model(self.save_model_path)
        self.model.load_state_dict(payload["state_dict"])
        history = {
            "seed": self.seed,
            "best_epoch": self.best_epoch,
            "best_validation_metrics": self.best_validation_metrics,
            "best_validation_score": self.best_validation_score,
            "stopped_early": stopped_early,
            "history": self.history,
        }
        with open(self.history_path, "w", encoding="utf-8") as handle:
            json.dump(history, handle, indent=2)
        print(f"[MLPTrainer] Best checkpoint saved to {self.save_model_path}")

    def evaluate(self):
        metrics = self._metrics(self.validation_features, self.validation_scores)
        print(f"[MLPTrainer] Validation metrics: {metrics}")
        return metrics["optimal_set_accuracy"]
