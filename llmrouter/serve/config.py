"""
Serve Configuration
===================
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import os
import yaml


@dataclass
class LLMConfig:
    """Single LLM configuration"""
    name: str
    provider: str
    model_id: str
    base_url: str
    api_key: Optional[str] = None
    input_price: float = 0.0
    output_price: float = 0.0
    max_tokens: int = 4096
    context_limit: int = 32768


@dataclass
class ServeConfig:
    """Server configuration"""
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000

    # Router settings
    router_name: str = "randomrouter"
    router_config_path: Optional[str] = None

    # LLM backend settings
    llms: Dict[str, LLMConfig] = field(default_factory=dict)

    # API Keys
    api_keys: Dict[str, List[str]] = field(default_factory=dict)

    # Show model name prefix
    show_model_prefix: bool = True

    # Backend resilience configuration.
    fallback_models: List[str] = field(default_factory=list)
    request_timeout_s: float = 120.0
    total_timeout_s: float = 180.0
    circuit_failure_threshold: int = 3
    circuit_cooldown_s: float = 30.0

    # Aggregate monitoring. Metrics fail closed unless the bearer-token
    # environment variable is configured by the deployment.
    metrics_enabled: bool = True
    metrics_token_env: str = "LLMROUTER_METRICS_TOKEN"
    metrics_persistence_path: Optional[str] = None
    quality_cascade_enabled: bool = False
    alert_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "all_chain_failure_rate": 0.005,
        "p95_latency_regression_fraction": 0.15,
        "circuit_open_rate": 0.02,
        "duplicate_calls_prevented": 0,
        "quality_escalation_rate": 0.25,
    })

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "ServeConfig":
        """Load configuration from YAML file"""
        if not os.path.exists(yaml_path):
            raise FileNotFoundError(f"Config file not found: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        config = cls()

        # Server settings
        serve_config = data.get("serve", {})
        config.host = serve_config.get("host", config.host)
        config.port = serve_config.get("port", config.port)
        config.show_model_prefix = serve_config.get("show_model_prefix", config.show_model_prefix)
        resilience = data.get("resilience", {})
        config.fallback_models = list(resilience.get("fallback_models", []))
        config.request_timeout_s = float(resilience.get("request_timeout_s", config.request_timeout_s))
        config.total_timeout_s = float(resilience.get("total_timeout_s", config.total_timeout_s))
        config.circuit_failure_threshold = int(resilience.get("circuit_failure_threshold", config.circuit_failure_threshold))
        config.circuit_cooldown_s = float(resilience.get("circuit_cooldown_s", config.circuit_cooldown_s))
        monitoring = data.get("monitoring", {})
        config.metrics_enabled = bool(monitoring.get("enabled", config.metrics_enabled))
        config.metrics_token_env = str(monitoring.get("token_env", config.metrics_token_env))
        config.metrics_persistence_path = monitoring.get("persistence_path", config.metrics_persistence_path)
        config.quality_cascade_enabled = bool(
            monitoring.get("quality_cascade_enabled", config.quality_cascade_enabled)
        )
        config.alert_thresholds.update(monitoring.get("alert_thresholds", {}))

        # Router settings
        router_config = data.get("router", {})
        config.router_name = router_config.get("name", config.router_name)
        config.router_config_path = router_config.get("config_path")

        # API Keys
        config.api_keys = data.get("api_keys", {})

        # LLM configuration
        llms_data = data.get("llms", {})
        for name, llm_config in llms_data.items():
            config.llms[name] = LLMConfig(
                name=name,
                provider=llm_config.get("provider", "openai"),
                model_id=llm_config.get("model", name),
                base_url=llm_config.get("base_url", "https://api.openai.com/v1"),
                api_key=llm_config.get("api_key"),
                input_price=llm_config.get("input_price", 0.0),
                output_price=llm_config.get("output_price", 0.0),
                max_tokens=llm_config.get("max_tokens", 4096),
                context_limit=llm_config.get("context_limit", 32768),
            )

        return config

    def get_api_key(self, provider: str) -> Optional[str]:
        """Get API key"""
        keys = self.api_keys.get(provider, [])
        if isinstance(keys, str):
            # Support environment variables
            if keys.startswith("${") and keys.endswith("}"):
                return os.environ.get(keys[2:-1])
            return keys
        elif isinstance(keys, list) and keys:
            # Round-robin multiple keys
            if not hasattr(self, "_key_index"):
                self._key_index = {}
            idx = self._key_index.get(provider, 0)
            key = keys[idx % len(keys)]
            self._key_index[provider] = idx + 1
            return key
        return None
