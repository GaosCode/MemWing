from __future__ import annotations

from memwing_benchmark.channels.feishu_cli import FeishuCli


def _new_feishu_cli(cli_bin: str):
    try:
        from memwing_benchmark import cli
    except Exception:
        return FeishuCli(cli_bin)
    return getattr(cli, "FeishuCli", FeishuCli)(cli_bin)
