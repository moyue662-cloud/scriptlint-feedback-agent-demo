"""DecisionPatch configuration.

All secrets (API keys) are read ONLY from environment variables.
Nothing sensitive is ever written into the repository, logs, or screenshots.
Spec reference: §8.3 隐私与安全.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_ROOT / "decisionpatch.db"

# --- Provider selection ---
# One of: "qiniu" | "mock". Default "mock" so the demo runs offline.
DEFAULT_PROVIDER = os.getenv("DP_PROVIDER", "mock")


@dataclass(frozen=True)
class QiniuConfig:
    """七牛云 OpenAI 兼容接口配置 (spec §0.2, §8.2)."""

    base_url: str = os.getenv("DP_QINIU_BASE_URL", "")
    api_key: str = os.getenv("DP_QINIU_API_KEY", "")
    model: str = os.getenv("DP_QINIU_MODEL", "")
    temperature: float = float(os.getenv("DP_MODEL_TEMPERATURE", "0.0"))

    @property
    def is_configured(self) -> bool:
        """True only when all required fields are present."""
        return bool(self.base_url and self.api_key and self.model)


@dataclass(frozen=True)
class AppConfig:
    """Top-level runtime configuration."""

    provider: str = DEFAULT_PROVIDER
    db_path: Path = DEFAULT_DB_PATH
    qiniu: QiniuConfig = field(default_factory=QiniuConfig)

    # Memory injection budget (spec §6.3: max 5 rules, ≤300 tokens)
    memory_max_rules: int = 5
    memory_max_tokens: int = 300
    memory_recall_topk: int = 8

    # LLM retry policy (spec §0.2: retry once, then explainable fallback)
    llm_max_retries: int = 1

    @property
    def effective_provider(self) -> str:
        """If qiniu is requested but not configured, fall back to mock."""
        if self.provider == "qiniu" and not self.qiniu.is_configured:
            return "mock"
        return self.provider


def load_config() -> AppConfig:
    """Build the runtime config from environment variables."""
    return AppConfig()


# Module-level singleton for convenience; tests may construct their own.
CONFIG = load_config()
