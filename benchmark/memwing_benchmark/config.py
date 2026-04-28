from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    openclaw: OpenClawConfig = Field(default_factory=OpenClawConfig)


def load_config(path: Path) -> BenchmarkConfig:
    path = path.expanduser()
    parsed = loads_json(path.read_bytes())
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return BenchmarkConfig.model_validate(parsed)


def sanitize_config_for_run(config: BenchmarkConfig) -> dict[str, Any]:
    data = config.model_dump(mode="json")
    data["judge"].pop("api_key", None)
    return data


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
