"""把 running 状态超过 30 分钟的任务标记为 abandoned。"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mobile_agent.config import cfg  # noqa: E402

THRESHOLD_MIN = 30


def main() -> None:
    cutoff = (datetime.utcnow() - timedelta(minutes=THRESHOLD_MIN)).isoformat()
    with sqlite3.connect(str(cfg.DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT id FROM tasks WHERE status='running' AND ts_start < ?",
            (cutoff,),
        ).fetchall()
        if not rows:
            print(f"没有超过 {THRESHOLD_MIN} 分钟的僵尸 running 任务")
            return
        ids = [r[0] for r in rows]
        conn.executemany(
            "UPDATE tasks SET status='abandoned', summary='startup cleanup', "
            "ts_end=? WHERE id=?",
            [(datetime.utcnow().isoformat(), tid) for tid in ids],
        )
        conn.commit()
    print(f"清理了 {len(ids)} 条僵尸任务: {ids}")


if __name__ == "__main__":
    main()
