"""
Gradio 双栏 UI:
  - 左:Chatbot,显示用户/Agent 消息
  - 右:当前手机截图(实时刷新),下方三个应急按钮

实现要点:
  - 用户提交消息 → 在后台线程跑 LangGraph
  - 主生成器每 1s 轮询当前任务目录的最新截图,yield 给右侧
  - 任务结束时 yield 最终回复
  - 应急按钮(停止/清后台/回桌面)绕过 Agent 直接操作 Device
"""
from __future__ import annotations

import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Generator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gradio as gr  # noqa: E402

from mobile_agent.agent.graph import get_app  # noqa: E402
from mobile_agent.agent.nodes import get_cancel_token, request_cancel  # noqa: E402
from mobile_agent.agent.state import AgentState  # noqa: E402
from mobile_agent.config import cfg  # noqa: E402


def _latest_shot(task_dir: Path) -> Path | None:
    if not task_dir.exists():
        return None
    shots = sorted(task_dir.glob("step_*.png"))
    return shots[-1] if shots else None


# ── 后台 worker ────────────────────────────────────
class _RunHolder:
    def __init__(self) -> None:
        self.task_id: str | None = None
        self.task_dir: Path | None = None
        self.final_reply: str | None = None
        self.error: str | None = None
        self.done = threading.Event()

    def reset(self) -> None:
        self.task_id = uuid.uuid4().hex[:12]
        self.task_dir = cfg.RUNS_DIR / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.final_reply = None
        self.error = None
        self.done.clear()


_current_run = _RunHolder()


def _worker(text: str, task_id: str) -> None:
    try:
        state: AgentState = {"user_input": text, "task_id": task_id}  # type: ignore[typeddict-item]
        out = get_app().invoke(state)
        _current_run.final_reply = out.get("final_reply") or "(无回复)"
    except Exception as e:
        _current_run.error = str(e)
        _current_run.final_reply = f"❌ 出错:{e}"
    finally:
        _current_run.done.set()


# ── Gradio handlers ────────────────────────────────
def chat_submit(message: str, history: list) -> Generator:
    if not message.strip():
        yield history, gr.update(), ""
        return

    _current_run.reset()
    task_id = _current_run.task_id
    assert task_id is not None
    history = history + [{"role": "user", "content": message}]
    yield history, gr.update(), ""

    th = threading.Thread(target=_worker, args=(message, task_id), daemon=True)
    th.start()

    last_shot: Path | None = None
    placeholder_added = False

    while not _current_run.done.is_set():
        shot = _latest_shot(_current_run.task_dir or Path("."))
        if shot and shot != last_shot:
            last_shot = shot
            if not placeholder_added:
                history.append(
                    {"role": "assistant", "content": f"_正在执行... 最新画面 {shot.name}_"}
                )
                placeholder_added = True
            else:
                history[-1] = {
                    "role": "assistant",
                    "content": f"_正在执行... 最新画面 {shot.name}_",
                }
            yield history, gr.update(value=str(shot)), ""
        else:
            yield history, gr.update(), ""
        time.sleep(0.8)

    th.join(timeout=2)
    final = _current_run.final_reply or "(无回复)"
    if placeholder_added:
        history[-1] = {"role": "assistant", "content": final}
    else:
        history.append({"role": "assistant", "content": final})

    final_shot = _latest_shot(_current_run.task_dir or Path(".")) or last_shot
    yield history, gr.update(value=str(final_shot) if final_shot else None), ""


# ── 应急按钮(绕过 Agent) ────────────────────────────
def _make_adhoc_device():
    from mobile_agent.device.device import Device

    return Device(task_dir=cfg.RUNS_DIR / f"adhoc-{uuid.uuid4().hex[:6]}")


def emergency_stop(history: list) -> tuple:
    if _current_run.task_id:
        request_cancel(_current_run.task_id, "user_stop_button")
    history = history + [{"role": "assistant", "content": "🛑 已请求停止当前任务。"}]
    return history, gr.update()


def emergency_clear_recent(history: list) -> tuple:
    try:
        d = _make_adhoc_device()
        d.clear_recent_apps()
        history = history + [{"role": "assistant", "content": "🧹 已清后台。"}]
    except Exception as e:
        history = history + [{"role": "assistant", "content": f"❌ 清后台失败:{e}"}]
    return history, gr.update()


def emergency_go_home(history: list) -> tuple:
    try:
        d = _make_adhoc_device()
        d.go_home()
        history = history + [{"role": "assistant", "content": "🏠 已回桌面。"}]
    except Exception as e:
        history = history + [{"role": "assistant", "content": f"❌ 回桌面失败:{e}"}]
    return history, gr.update()


# ── UI 构建 ───────────────────────────────────────
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="手机操作 Agent") as demo:
        gr.Markdown("# 📱 手机操作 Agent (MVP)")

        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    label="对话", height=560,
                    avatar_images=(None, None),
                )
                msg = gr.Textbox(
                    placeholder="例:用'独居老人陪伴'主题发一条小红书文字笔记 / 你好 / 停",
                    label="输入", lines=2,
                )
                with gr.Row():
                    send_btn = gr.Button("发送", variant="primary")
                    clear_btn = gr.Button("清空对话")
            with gr.Column(scale=2):
                screen = gr.Image(
                    label="当前手机截图", height=560,
                    show_label=True, interactive=False, type="filepath",
                )
                with gr.Row():
                    stop_btn = gr.Button("🛑 停止", variant="stop")
                    home_btn = gr.Button("🏠 回桌面")
                    recent_btn = gr.Button("🧹 清后台")
                gr.Markdown(
                    "_应急按钮绕过 Agent 直接调用 Device,只在 USB 真机连接时可用。_"
                )

        # 事件
        send_btn.click(
            chat_submit, inputs=[msg, chatbot], outputs=[chatbot, screen, msg]
        )
        msg.submit(
            chat_submit, inputs=[msg, chatbot], outputs=[chatbot, screen, msg]
        )
        clear_btn.click(lambda: ([], None), inputs=None, outputs=[chatbot, screen])
        stop_btn.click(emergency_stop, inputs=[chatbot], outputs=[chatbot, screen])
        home_btn.click(emergency_go_home, inputs=[chatbot], outputs=[chatbot, screen])
        recent_btn.click(
            emergency_clear_recent, inputs=[chatbot], outputs=[chatbot, screen]
        )

    return demo


def main() -> None:
    demo = build_ui()
    demo.queue()
    demo.launch(
        server_name="127.0.0.1", server_port=7860, inbrowser=True,
        theme=gr.themes.Soft(),
    )


if __name__ == "__main__":
    main()
