from pathlib import Path

import pytest


INTEGRATION_DIRECTORIES = {"inference_test", "train_test"}


def pytest_collection_modifyitems(items):
    """Keep model-, API-, and service-backed scripts out of offline test runs."""
    integration = pytest.mark.integration
    for item in items:
        path_parts = Path(str(item.path)).parts
        if INTEGRATION_DIRECTORIES.intersection(path_parts):
            item.add_marker(integration)
