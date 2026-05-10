"""
M5 记忆层验证脚本。

输出:
  - 会话历史(最近 10 条)
  - 任务历史(最近 5 条 + 最近一次成功的任务详情)
  - 用户事实(facts 表所有键值)
  - 已注册技能
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mobile_agent.config import cfg  # noqa: E402
from mobile_agent.memory.db import get_memory  # noqa: E402


def main() -> None:
    print(f"DB: {cfg.DB_PATH}")
    print(f"DB 存在: {cfg.DB_PATH.exists()}")
    if not cfg.DB_PATH.exists():
        print("还没生成数据库,跑一次 Agent 后再测。")
        return
    print()

    mem = get_memory()

    # 会话
    print("=== 会话历史(最近 10 条) ===")
    msgs = mem.recent_messages(10)
    if not msgs:
        print("  (空)")
    for m in msgs:
        content = m["content"][:70].replace("\n", " ")
        print(f"  [{m['role']:9}] {content}")
    print()

    # 任务
    print("=== 任务历史(最近 5 条) ===")
    with sqlite3.connect(str(cfg.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, ts_start, status, skill, summary FROM tasks "
            "ORDER BY ts_start DESC LIMIT 5"
        ).fetchall()
    if not rows:
        print("  (空)")
    for r in rows:
        s = (r["summary"] or "")[:60].replace("\n", " ")
        print(f"  [{r['status']:9}] {r['ts_start'][:19]} {r['skill']}  {s}")
    print()

    # 最近一次成功
    last = mem.last_success_task()
    print("=== 最近一次成功任务 ===")
    if last:
        print(f"  id     : {last['id']}")
        print(f"  skill  : {last['skill']}")
        print(f"  args   : {last.get('args', {})}")
        print(f"  summary: {last.get('summary', '')[:200]}")
    else:
        print("  (没有成功的任务)")
    print()

    # 事实
    print("=== 用户事实 (facts) ===")
    facts = mem.all_facts()
    if not facts:
        print("  (空)")
    for k, v in facts.items():
        print(f"  {k:25} = {v[:80]}")
    print()

    # 技能
    print("=== 已注册技能 ===")
    with sqlite3.connect(str(cfg.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT name, description, enabled FROM skills"
        ).fetchall()
    if not rows:
        print("  (空 — 跑一次 Agent 后会自动注册)")
    for r in rows:
        print(f"  [{('on' if r['enabled'] else 'off'):3}] {r['name']:35} {r['description'][:60]}")


if __name__ == "__main__":
    main()
