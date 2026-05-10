"""LangGraph 编排:5 节点 + 1 条件路由。"""
from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from mobile_agent.agent.nodes import (
    cancel_handler,
    chat_reply,
    load_context,
    route,
    run_skill,
    summarize,
)
from mobile_agent.agent.state import AgentState


def _branch(state: AgentState) -> Literal["chat", "skill", "cancel"]:
    intent = state.get("intent")
    if intent == "call_skill":
        return "skill"
    if intent == "cancel":
        return "cancel"
    return "chat"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("load_context", load_context)
    g.add_node("route", route)
    g.add_node("chat_reply", chat_reply)
    g.add_node("run_skill", run_skill)
    g.add_node("cancel_handler", cancel_handler)
    g.add_node("summarize", summarize)

    g.add_edge(START, "load_context")
    g.add_edge("load_context", "route")
    g.add_conditional_edges(
        "route",
        _branch,
        {
            "chat": "chat_reply",
            "skill": "run_skill",
            "cancel": "cancel_handler",
        },
    )
    g.add_edge("chat_reply", "summarize")
    g.add_edge("run_skill", "summarize")
    g.add_edge("cancel_handler", "summarize")
    g.add_edge("summarize", END)

    return g.compile()


_compiled = None


def get_app():
    """单例:首次调用时编译。"""
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled
