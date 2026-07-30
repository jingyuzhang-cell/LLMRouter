from pathlib import Path

import numpy as np

from llmrouter.models import MLPRouter


CONFIG = "configs/model_config_test/mlprouter_soft.yaml"


def test_soft_checkpoint_contains_inference_metadata():
    router = MLPRouter(CONFIG)
    router.load_model_path = router._model_path()
    model, model_type = router._load_mlp_model()

    assert model_type == "soft_pytorch"
    assert router.checkpoint_metadata["format_version"] == 2
    assert router.checkpoint_metadata["objective"] == "soft_performance_distribution"
    assert router.checkpoint_metadata["soft_label_temperature"] == 0.03
    assert router.checkpoint_metadata["tie_soft_blend"] == 0.2
    assert router.checkpoint_metadata["clear_gap_weight"] == 3.0
    assert router.checkpoint_metadata["regret_loss_weight"] == 1.0
    assert len(router.checkpoint_metadata["embedding_mean"]) == router.embedding_dim
    assert len(router.checkpoint_metadata["normalized_costs"]) == len(router.model_names)

    sample = router.routing_data_test.iloc[0]
    embedding = router.query_embedding_data[int(sample["embedding_id"])]
    selected, scores, costs, utilities = router._select_model(
        model, model_type, embedding, sample["task_name"]
    )

    assert selected in router.model_names
    assert np.isclose(scores.sum(), 1.0)
    assert len(scores) == len(costs) == len(utilities) == len(router.model_names)
