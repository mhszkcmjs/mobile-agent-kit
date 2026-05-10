"""
LangGraph 节点实现。M5 起接入 SQLite 记忆。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from mobile_agent.agent.state import AgentState
from mobile_agent.config import cfg
from mobile_agent.constants import LLM_TEMPERATURE_ROUTER
from mobile_agent.device.device import Device
from mobile_agent.llm.kimi_client import get_kimi
from mobile_agent.memory.db import get_memory
from mobile_agent.memory.facts import extract_and_save
from mobile_agent.skills import SkillRegistry, autoload
from mobile_agent.skills.base import RunContext
from mobile_agent.utils.cancel import CancelToken
from mobile_agent.utils.logger import get_logger


_ROUTER_PROMPT_PATH = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "router.md"
_LOG = get_logger("agent")


_REGISTRY: SkillRegistry | None = None
_CANCEL_TOKENS: dict[str, CancelToken] = {}


def get_registry() -> SkillRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = autoload()
        # 启动时把技能元数据同步到 DB(供后台审计)
        try:
            get_memory().sync_skills(_REGISTRY.descriptions())
        except Exception as e:
            _LOG.warning(f"同步技能到 DB 失败(忽略):{e}")
    return _REGISTRY


def get_cancel_token(task_id: str) -> CancelToken:
    if task_id not in _CANCEL_TOKENS:
        _CANCEL_TOKENS[task_id] = CancelToken()
    return _CANCEL_TOKENS[task_id]


def request_cancel(task_id: str, reason: str = "user_requested") -> None:
    if task_id in _CANCEL_TOKENS:
        _CANCEL_TOKENS[task_id].cancel(reason)


# ── 节点 ────────────────────────────────────────────
def load_context(state: AgentState) -> AgentState:
    mem = get_memory()
    state["conversation"] = list(mem.recent_messages(20))
    state["user_facts"] = dict(mem.all_facts())
    if "task_id" not in state or not state.get("task_id"):
        state["task_id"] = uuid.uuid4().hex[:12]
    return state


def route(state: AgentState) -> AgentState:
    user_input = state["user_input"]
    mem = get_memory()
    mem.append_message("user", user_input, task_id=state.get("task_id"))

    convo_str = "\n".join(
        f"{m['role']}: {m['content']}" for m in state.get("conversation", [])
    ) or "(空)"
    facts_str = json.dumps(state.get("user_facts", {}), ensure_ascii=False) or "{}"
    skills_json = json.dumps(get_registry().descriptions(), ensure_ascii=False)

    prompt = _ROUTER_PROMPT_PATH.read_text(encoding="utf-8").format(
        conversation=convo_str,
        facts=facts_str,
        skills_json=skills_json,
    )

    try:
        raw = get_kimi().chat(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=LLM_TEMPERATURE_ROUTER,
            json_mode=True,
        )
        data = json.loads(raw)
    except Exception as e:
        _LOG.warning(f"router 失败,降级为 chat:{e}")
        data = {"intent": "chat", "reply": "我没听清,能再说一次吗?"}

    intent = data.get("intent", "chat")
    if intent not in ("chat", "call_skill", "cancel"):
        intent = "chat"
    state["intent"] = intent
    state["router_reply"] = data.get("reply")
    if intent == "call_skill":
        state["skill_call"] = {
            "name": data.get("skill"),
            "args": data.get("args", {}),
        }
    return state


def chat_reply(state: AgentState) -> AgentState:
    state["final_reply"] = state.get("router_reply") or "好的。"
    return state


def run_skill(state: AgentState) -> AgentState:
    call = state.get("skill_call") or {}
    skill_name = call.get("name")
    args_dict = call.get("args", {}) or {}

    skill = get_registry().get(skill_name or "")
    if skill is None:
        state["final_reply"] = f"未知技能:{skill_name}"
        state["skill_result"] = {"ok": False, "summary": "skill not found"}
        return state

    try:
        args_obj = skill.args_schema.model_validate(args_dict)
    except Exception as e:
        state["final_reply"] = f"参数不对:{e}"
        state["skill_result"] = {"ok": False, "summary": str(e)}
        return state

    task_id = state["task_id"]
    task_dir = cfg.RUNS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    cancel = get_cancel_token(task_id)
    logger = get_logger(f"task.{task_id}", task_dir=task_dir)
    mem = get_memory()
    mem.task_start(task_id, skill_name or "?", args_dict, task_dir)

    device = Device(task_dir=task_dir, cancel_token=cancel)
    ctx = RunContext(
        device=device,
        task_id=task_id,
        task_dir=task_dir,
        cancel_token=cancel,
        logger=logger,
        memory=mem,
    )

    prefix = state.get("router_reply") or ""
    try:
        with device.session():
            result = skill.run(args_obj, ctx)
        state["skill_result"] = {
            "ok": result.ok,
            "summary": result.summary,
            "extra": result.extra,
        }
        state["artifacts"] = [str(p) for p in result.artifacts]
        state["final_reply"] = (
            f"{prefix}\n✅ {result.summary}" if prefix else f"✅ {result.summary}"
        )
        mem.task_finish(task_id, "success", result.summary)
    except Exception as e:
        logger.exception(f"技能 {skill_name} 执行失败")
        state["skill_result"] = {"ok": False, "summary": str(e)}
        state["final_reply"] = f"❌ 任务失败:{e}\n手机已尝试回桌面。"
        if cancel.cancelled:
            mem.task_finish(task_id, "cancelled", str(e))
        else:
            mem.task_finish(task_id, "failed", str(e))
    return state


def cancel_handler(state: AgentState) -> AgentState:
    for tid, token in _CANCEL_TOKENS.items():
        if not token.cancelled:
            token.cancel("user_requested")
    state["final_reply"] = state.get("router_reply") or "好,已停止。"
    state["cancel_requested"] = True
    return state


def summarize(state: AgentState) -> AgentState:
    reply = state.get("final_reply") or "好的。"
    mem = get_memory()
    mem.append_message("assistant", reply, task_id=state.get("task_id"))

    # 事实抽取(失败不影响主流程)
    try:
        new_facts = extract_and_save(state.get("user_input", ""))
        if new_facts:
            _LOG.info(f"记住事实:{new_facts}")
    except Exception as e:
        _LOG.debug(f"事实抽取失败(忽略):{e}")

    return state
