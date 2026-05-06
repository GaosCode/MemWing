from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memwing_benchmark.adapters.openclaw_native import OpenClawNativeAdapter
from memwing_benchmark.channels.feishu_cli import FeishuCli
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.metrics.retrieval import unique_preserve_order
from memwing_benchmark.run_support import (
    confirm_side_effect,
    debug,
    required_feishu_scopes,
)


@dataclass(frozen=True)
class LiveChatIds:
    seed_chat_id: str
    probe_chat_id: str


@dataclass(frozen=True)
class LiveWorkspaceRestore:
    original_workspace: str
    memory_flush_touched: bool
    memory_flush_present: bool
    memory_flush_value: Any = None


def prepare_live_workspace(
    *,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
    run_dir: Path,
    force_memory_flush: bool,
    yes: bool,
) -> LiveWorkspaceRestore:
    debug(raw_records, "读取 OpenClaw 当前 workspace")
    original_workspace = adapter.get_default_workspace()
    original_memory_flush = None
    if force_memory_flush:
        debug(raw_records, "读取 OpenClaw memoryFlush 配置", workspace=original_workspace)
        original_memory_flush = adapter.get_config_value("agents.defaults.compaction.memoryFlush")
    workspace_dir = run_dir / "openclaw-workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    confirm_side_effect(
        "切换 OpenClaw 到本轮 benchmark 独立 workspace 并重启 gateway",
        yes,
    )
    debug(raw_records, "切换 OpenClaw workspace", workspace=str(workspace_dir))
    adapter.set_default_workspace(workspace_dir)
    if force_memory_flush:
        next_memory_flush = (
            dict(original_memory_flush.value)
            if isinstance(original_memory_flush.value, dict)
            else {}
        )
        next_memory_flush["enabled"] = True
        next_memory_flush["forceFlushTranscriptBytes"] = 1
        debug(raw_records, "写入 OpenClaw memoryFlush 配置", value=next_memory_flush)
        adapter.set_config_json("agents.defaults.compaction.memoryFlush", next_memory_flush)
    debug(raw_records, "重启 OpenClaw gateway 以加载 workspace")
    adapter.restart_gateway()
    raw_records["side_effects"].append(
        {
            "action": "isolate_openclaw_workspace",
            "original_workspace": original_workspace,
            "workspace": str(workspace_dir),
        }
    )
    if original_memory_flush is not None:
        raw_records["side_effects"].append(
            {
                "action": "force_openclaw_memory_flush",
                "path": "agents.defaults.compaction.memoryFlush",
                "original_present": original_memory_flush.present,
            }
        )
    return LiveWorkspaceRestore(
        original_workspace=original_workspace,
        memory_flush_touched=original_memory_flush is not None,
        memory_flush_present=original_memory_flush.present if original_memory_flush else False,
        memory_flush_value=original_memory_flush.value if original_memory_flush else None,
    )


def restore_live_workspace(
    *,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
    restore: LiveWorkspaceRestore,
) -> None:
    debug(raw_records, "恢复 OpenClaw workspace", workspace=restore.original_workspace)
    adapter.set_default_workspace(Path(restore.original_workspace))
    if restore.memory_flush_touched:
        if restore.memory_flush_present:
            debug(
                raw_records,
                "恢复 OpenClaw memoryFlush 配置",
                value=restore.memory_flush_value,
            )
            adapter.set_config_json(
                "agents.defaults.compaction.memoryFlush",
                restore.memory_flush_value,
            )
        else:
            debug(raw_records, "删除临时 OpenClaw memoryFlush 配置")
            adapter.unset_config_value("agents.defaults.compaction.memoryFlush")
    debug(raw_records, "重启 OpenClaw gateway 以恢复原配置")
    adapter.restart_gateway()
    raw_records["side_effects"].append(
        {"action": "restore_openclaw_workspace", "workspace": restore.original_workspace}
    )
    if restore.memory_flush_touched:
        raw_records["side_effects"].append(
            {
                "action": "restore_openclaw_memory_flush",
                "path": "agents.defaults.compaction.memoryFlush",
                "restored_present": restore.memory_flush_present,
            }
        )


def prepare_live_chat(
    *,
    config,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
    run_id: str,
    create_chat: bool,
    configure_openclaw: bool,
    restart_gateway: bool,
    require_mention: bool,
    yes: bool,
) -> LiveChatIds:
    debug(raw_records, "准备 Feishu live 群")
    feishu = FeishuCli(config.feishu.cli_bin)
    should_create = create_chat or config.feishu.create_chat_if_missing
    if not should_create:
        raise BenchmarkError(
            "formal live cross_chat_durable requires fresh seed/probe chats for every run; "
            "use --create-chat or set feishu.create_chat_if_missing=true"
        )
    required_scopes = required_feishu_scopes(will_create_chat=True)
    debug(raw_records, "检查 Feishu CLI 登录和 scope", scopes=required_scopes)
    feishu.ensure_ready(required_scopes=required_scopes)
    created_chat_ids: list[str] = []
    confirm_side_effect("创建飞书 seed/probe 两个测试群并邀请机器人", yes)
    debug(raw_records, "读取 Feishu CLI 当前 app id")
    cli_bot_app_id = feishu.current_app_id()
    debug(raw_records, "Feishu CLI app id 已读取", cli_bot_app_id=cli_bot_app_id)
    seed_chat_id = _create_named_chat(
        feishu=feishu,
        config=config,
        run_id=run_id,
        role="Seed",
        cli_bot_app_id=cli_bot_app_id,
        raw_records=raw_records,
    )
    created_chat_ids.append(seed_chat_id)
    debug(raw_records, "Seed 群创建完成", chat_id=seed_chat_id)
    probe_chat_id = _create_named_chat(
        feishu=feishu,
        config=config,
        run_id=run_id,
        role="Probe",
        cli_bot_app_id=cli_bot_app_id,
        raw_records=raw_records,
    )
    created_chat_ids.append(probe_chat_id)
    debug(raw_records, "Probe 群创建完成", chat_id=probe_chat_id)
    if seed_chat_id == probe_chat_id:
        raise BenchmarkError(
            "cross_chat_durable requires different feishu.seed_chat_id and feishu.probe_chat_id"
        )
    allowlist_chat_ids = (
        [seed_chat_id, probe_chat_id]
        if configure_openclaw or config.openclaw.configure_allowlist
        else created_chat_ids
    )
    if allowlist_chat_ids:
        confirm_side_effect("修改 OpenClaw 飞书 group allowlist/config", yes)
        configured_chat_ids = unique_preserve_order(allowlist_chat_ids)
        debug(raw_records, "配置 OpenClaw 飞书群 allowlist", chat_ids=configured_chat_ids)
        adapter.configure_feishu_groups(configured_chat_ids, require_mention=require_mention)
        for chat_id in configured_chat_ids:
            raw_records["side_effects"].append(
                {
                    "action": "configure_openclaw",
                    "chat_id": chat_id,
                    "require_mention": require_mention,
                }
            )
    if restart_gateway or config.openclaw.restart_gateway:
        confirm_side_effect("重启 OpenClaw gateway", yes)
        debug(raw_records, "重启 OpenClaw gateway 以加载群配置")
        adapter.restart_gateway()
        raw_records["side_effects"].append({"action": "restart_gateway"})
    raw_records["feishu_commands"].extend(
        command.model_dump(mode="json") for command in feishu.commands
    )
    return LiveChatIds(seed_chat_id=seed_chat_id, probe_chat_id=probe_chat_id)


def prepare_write_ingest_chat(
    *,
    config,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
    run_id: str,
    create_chat: bool,
    configure_openclaw: bool,
    restart_gateway: bool,
    yes: bool,
) -> LiveChatIds:
    debug(raw_records, "准备 Feishu write ingest 群")
    feishu = FeishuCli(config.feishu.cli_bin)
    should_create = create_chat or config.feishu.create_chat_if_missing
    if should_create:
        required_scopes = required_feishu_scopes(will_create_chat=True)
        debug(raw_records, "检查 Feishu CLI 登录和 scope", scopes=required_scopes)
        feishu.ensure_ready(required_scopes=required_scopes)
        confirm_side_effect("创建飞书 write ingest 测试群并邀请机器人", yes)
        debug(raw_records, "读取 Feishu CLI 当前 app id")
        cli_bot_app_id = feishu.current_app_id()
        debug(raw_records, "Feishu CLI app id 已读取", cli_bot_app_id=cli_bot_app_id)
        chat_id = _create_named_chat(
            feishu=feishu,
            config=config,
            run_id=run_id,
            role="Ingest",
            cli_bot_app_id=cli_bot_app_id,
            raw_records=raw_records,
        )
        debug(raw_records, "Ingest 群创建完成", chat_id=chat_id)
    else:
        chat_id = config.feishu.seed_chat_id or config.feishu.chat_id
        if not chat_id:
            raise BenchmarkError(
                "write ingest requires --chat-id, feishu.chat_id, or --create-chat"
            )
        debug(raw_records, "使用已有 Feishu write ingest 群", chat_id=chat_id)
        feishu.ensure_ready(required_scopes=required_feishu_scopes(will_create_chat=False))

    if configure_openclaw or config.openclaw.configure_allowlist or should_create:
        confirm_side_effect("修改 OpenClaw 飞书 group allowlist/config", yes)
        debug(raw_records, "配置 OpenClaw 飞书 ingest 群 allowlist", chat_id=chat_id)
        adapter.configure_feishu_group(chat_id, require_mention=False)
        raw_records["side_effects"].append(
            {
                "action": "configure_openclaw",
                "chat_id": chat_id,
                "require_mention": False,
            }
        )
    if restart_gateway or config.openclaw.restart_gateway or should_create:
        confirm_side_effect("重启 OpenClaw gateway", yes)
        debug(raw_records, "重启 OpenClaw gateway 以加载 ingest 群配置")
        adapter.restart_gateway()
        raw_records["side_effects"].append({"action": "restart_gateway"})
    raw_records["feishu_commands"].extend(
        command.model_dump(mode="json") for command in feishu.commands
    )
    return LiveChatIds(seed_chat_id=chat_id, probe_chat_id=chat_id)


def _create_named_chat(
    *,
    feishu: FeishuCli,
    config,
    run_id: str,
    role: str,
    cli_bot_app_id: str,
    raw_records: dict[str, Any],
) -> str:
    debug(
        raw_records,
        f"开始创建 {role} 群",
        name=f"{config.feishu.chat_name_prefix} {run_id} {role}",
        bot_app_ids=[config.feishu.bot_app_id, cli_bot_app_id],
    )
    created = feishu.create_chat(
        name=f"{config.feishu.chat_name_prefix} {run_id} {role}",
        bot_app_ids=[config.feishu.bot_app_id, cli_bot_app_id],
    )
    chat_id = str(created["chat_id"])
    raw_records["side_effects"].append(
        {"action": f"create_{role.lower()}_chat", "chat_id": chat_id}
    )
    return chat_id
