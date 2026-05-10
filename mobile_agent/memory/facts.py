"""
事实抽取:每轮对话结束后调一次,把"稳定事实"写入 facts 表。

对错失败、API 不稳都不影响主流程 —— 上层用 try/except 包住即可。
"""
from __future__ import annotations

import json
from pathlib import Path

from mobile_agent.llm.kimi_client import get_kimi
from mobile_agent.memory.db import get_memory


_PROMPT_PATH = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "fact_extract.md"


def extract_and_save(user_message: str) -> list[tuple[str, str]]:
    """从 user_message 抽事实并写入 facts 表。返回新增/更新的 (key, value) 列表。"""
    if not user_message.strip():
        return []
    mem = get_memory()
    known = mem.all_facts()
    prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
        message=user_message,
        known_facts=json.dumps(known, ensure_ascii=False),
    )
    try:
        data = get_kimi().chat_json(
            [{"role": "user", "content": prompt}], temperature=0
        )
    except Exception:
        return []

    written: list[tuple[str, str]] = []
    for f in data.get("facts", []) or []:
        key = (f.get("key") or "").strip()
        value = (f.get("value") or "").strip()
        if not key or not value:
            continue
        # 限制 key 命名(蛇形,英文+数字+下划线)
        if not all(c.isalnum() or c == "_" for c in key):
            continue
        if known.get(key) == value:
            continue  # 无变化
        mem.upsert_fact(key, value, source="agent_inferred")
        written.append((key, value))
    return written
