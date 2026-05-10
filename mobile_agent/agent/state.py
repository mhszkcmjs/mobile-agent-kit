"""LangGraph 状态定义。"""
from __future__ import annotations

from typing import Any, Literal, TypedDict


class Message(TypedDict):
    role: Literal["user", "assistant", "system"]
    content: str


class AgentState(TypedDict, total=False):
    # 输入
    user_input: str

    # 上下文
    conversation: list[Message]
    user_facts: dict[str, str]

    # 路由结果
    intent: Literal["chat", "call_skill", "cancel"] | None
    skill_call: dict[str, Any] | None  # {"name": str, "args": dict}
    router_reply: str | None

    # 执行结果
    skill_result: dict[str, Any] | None
    final_reply: str | None
    artifacts: list[str] | None  # 截图绝对路径

    # 控制
    cancel_requested: bool
    task_id: str
