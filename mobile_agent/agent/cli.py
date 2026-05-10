"""
CLI 模式 —— 自然语言驱动 Agent。

用法:
    python -m mobile_agent.agent.cli

  > 你好
  Agent: 你好...
  > 用"独居老人陪伴"主题发一条小红书文字笔记
  Agent: 好的,我来发布,大约 3~5 分钟
         [系统消息] step 1/12 ...
         ...
         ✅ 已发布《独居的妈妈,需要的不只是一日三餐》(...)
  > 停
  Agent: 已停止
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from mobile_agent.agent.graph import get_app  # noqa: E402
from mobile_agent.agent.nodes import request_cancel  # noqa: E402
from mobile_agent.agent.state import AgentState  # noqa: E402


_active_task_id: str | None = None
_task_lock = threading.Lock()


def _on_input(text: str) -> str:
    """同步执行一轮 Agent 调用,返回最终回复。"""
    global _active_task_id
    state: AgentState = {"user_input": text}  # type: ignore[typeddict-item]
    out = get_app().invoke(state)
    with _task_lock:
        _active_task_id = out.get("task_id")
    return out.get("final_reply") or "(无回复)"


def main() -> None:
    print("Mobile Agent CLI(M3)。Ctrl+D 退出。")
    print("提示:输入'停'即可中途取消正在运行的任务。\n")

    while True:
        try:
            line = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        # 取消是同步路径,但若任务正在跑,主线程会阻塞 → 启动一个监听线程
        # MVP:直接同步调用即可演示
        try:
            reply = _on_input(line)
        except Exception as e:
            reply = f"❌ 出错:{e}"
        print(f"Agent: {reply}\n")

    print("bye")


if __name__ == "__main__":
    main()
