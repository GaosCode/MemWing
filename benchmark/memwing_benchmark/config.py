from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.json_utils import loads_json


class JudgeConfig(BaseModel):
    provider: str = "volcengine_ark"
    api_key: str = ""
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    model: str = ""
    temperature: float = 0

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key and not self.api_key.startswith("填"))


class PathsConfig(BaseModel):
    openclaw_repo_dir: str = ""
    memwing_repo_dir: str = ""
    runs_dir: str = "runs"


class FeishuConfig(BaseModel):
    cli_bin: str = "lark-cli"
    bot_app_id: str = ""
    bot_open_id: str = ""
    bot_name: str = ""
    mention_text: str = ""
    chat_id: str = ""
    seed_chat_id: str = ""
    probe_chat_id: str = ""
    create_chat_if_missing: bool = False
    chat_name_prefix: str = "MemWing Bench"


class OpenClawConfig(BaseModel):
    agent_id: str = "main"
    trajectory_dir: str = ""
    configure_allowlist: bool = False
    restart_gateway: bool = False
    workspace_dir: str = ""


class MemWingConfig(BaseModel):
    base_url: str = ""
    agent_id: str = "main"
    workspace_id: str = "workspace_001"
    session_id: str = "memwing-benchmark"
    project_memory_space_id: str = "project_001"
    group_id: str = "benchmark_group"
    thread_id: str = "benchmark_thread"
    shared_group_id: str = ""
    safe_mode: bool = False
    ingest_timeout_seconds: float = 30
    search_timeout_seconds: float = 30
    settle_seconds: float = 2
    poll_interval_seconds: float = 2
    poll_timeout_seconds: float = 60

    @field_validator(
        "ingest_timeout_seconds",
        "search_timeout_seconds",
        "settle_seconds",
        "poll_interval_seconds",
        "poll_timeout_seconds",
    )
    @classmethod
    def _validate_non_negative_seconds(cls, value: float) -> float:
        if value < 0:
            raise ValueError("timeout and interval values must be non-negative")
        return value

    @property
    def normalized_base_url(self) -> str:
        return self.base_url.strip().rstrip("/")


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    openclaw: OpenClawConfig = Field(default_factory=OpenClawConfig)
    memwing: MemWingConfig = Field(default_factory=MemWingConfig)


def load_config(path: Path) -> BenchmarkConfig:
    path = path.expanduser()
    parsed = loads_json(path.read_bytes())
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return BenchmarkConfig.model_validate(parsed)


def sanitize_config_for_run(config: BenchmarkConfig) -> dict[str, Any]:
    data = config.model_dump(mode="json")
    data["judge"].pop("api_key", None)
    _redact_keys(
        data.get("feishu"),
        {
            "bot_app_id",
            "bot_open_id",
            "mention_text",
            "chat_id",
            "seed_chat_id",
            "probe_chat_id",
        },
    )
    memwing = data.get("memwing")
    if isinstance(memwing, dict):
        memwing["base_url"] = _sanitize_url(memwing.get("base_url"))
        _redact_keys(
            memwing,
            {
                "group_id",
                "thread_id",
                "shared_group_id",
            },
        )
    return data


def validate_config_for_backend(config: BenchmarkConfig, *, backend: str) -> None:
    if backend == "memwing":
        if not config.memwing.normalized_base_url:
            raise BenchmarkError("memwing.base_url is required for --backend memwing")
        if not config.memwing.project_memory_space_id.strip():
            raise BenchmarkError("memwing.project_memory_space_id is required")
        if not config.memwing.group_id.strip():
            raise BenchmarkError("memwing.group_id is required")
        if not config.memwing.thread_id.strip():
            raise BenchmarkError("memwing.thread_id is required")


def _redact_keys(section: object, keys: set[str]) -> None:
    if not isinstance(section, dict):
        return
    for key in keys:
        if key in section:
            section[key] = ""


def _sanitize_url(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    value = value.strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.username is None and parsed.password is None:
        return value
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def apply_overrides(
    config: BenchmarkConfig,
    *,
    runs_dir: Path | None = None,
    chat_id: str | None = None,
    trajectory_dir: Path | None = None,
) -> BenchmarkConfig:
    updates: dict[str, Any] = {}
    if runs_dir is not None:
        paths = config.paths.model_copy(update={"runs_dir": str(runs_dir)})
        updates["paths"] = paths
    if chat_id is not None:
        feishu = config.feishu.model_copy(update={"chat_id": chat_id})
        updates["feishu"] = feishu
    if trajectory_dir is not None:
        openclaw = config.openclaw.model_copy(update={"trajectory_dir": str(trajectory_dir)})
        updates["openclaw"] = openclaw
    return config.model_copy(update=updates)
