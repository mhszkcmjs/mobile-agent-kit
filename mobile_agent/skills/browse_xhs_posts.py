"""
浏览小红书推送笔记并提取关键信息。

流程:
  0. 前置:adb 直接打开小红书
  1. VLM 自主刷推荐流,逐条进入笔记 → 阅读 → 用 report 动作上报关键内容
  2. 累计 N 条后自行 done
  3. 技能层把所有 report 汇总返回给用户
"""
from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field

from mobile_agent.config import cfg
from mobile_agent.constants import XHS_PACKAGE
from mobile_agent.device.device import Device
from mobile_agent.device.vlm_loop import StateDef, VLMLoopError, run_vlm_loop
from mobile_agent.skills.base import RunContext, SkillResult


# A2 状态机定义
BROWSE_STATES = [
    StateDef("FEED", "停在小红书推荐流;选一条还没读过的笔记 tap_id 点进去"),
    StateDef("READING", "正在笔记详情页阅读内容;必要时 swipe up 翻看完整正文"),
    StateDef("REPORT", "用 report 动作上报本条笔记的核心信息(标题+1~2句要点)"),
    StateDef("BACK_TO_FEED", "press_key BACK 返回推荐流;swipe up 一下避免下次还点同一条"),
]


class BrowseXhsArgs(BaseModel):
    count: int = Field(2, ge=1, le=10, description="要阅读的笔记条数(1~10)")
    topic: str | None = Field(
        None,
        description="可选话题/方向偏好,例如'美食'/'职场'/'独居老人';留空则读默认推荐流",
    )


def _build_goal(count: int, topic: str | None) -> str:
    topic_hint = (
        f"\n【偏好方向】优先选取与「{topic}」相关的笔记,无相关时也接受其他笔记。"
        if topic else ""
    )
    return f"""你已经在小红书 App 内(已自动打开)。请完成以下任务:浏览推荐流并阅读 {count} 条笔记的内容,把每条的核心有用信息上报。
{topic_hint}

【操作建议】
- 当前应该在小红书首页/推荐流。如果不在,先 tap_text "首页" 或 "推荐"
- 每读一条笔记的标准流程:
  1. tap 一条笔记缩略图进入详情页
  2. 阅读标题 + 正文(必要时 swipe up 向下翻看完整内容)
  3. 用 **report** 动作上报这条笔记的核心信息(标题 + 1~2 句要点)
  4. press_key BACK 返回推荐流
  5. swipe up 翻一下,避免下次还点同一条
- 累计上报 {count} 条后,输出 done

【report 动作示例】
{{"action": "report", "params": {{"text": "《标题XXX》:核心要点是...,有用之处在于..."}}, "description": "上报第N条笔记"}}

【硬约束】
- 必须用 report 上报,不要把内容写在 description 里
- 如果遇到弹窗/广告/登录提示,先关掉再继续
- 不要点 + 号、不要发布,只读不写
"""


class _BrowseXhsPosts:
    name = "browse_xhs_posts"
    description = (
        "浏览小红书推荐流并阅读 N 条笔记,把核心有用信息汇总返回给用户。"
        "适合'帮我刷两条小红书看看'/'看看最近 X 话题的推送'这类需求。"
    )
    args_schema = BrowseXhsArgs

    def run(self, args: BrowseXhsArgs, ctx: RunContext) -> SkillResult:  # type: ignore[override]
        device: Device = ctx.device
        log = ctx.logger

        # 前置:打开 App
        log.info(f"前置:launch_app {XHS_PACKAGE}")
        device.launch_app(XHS_PACKAGE)
        time.sleep(2)
        if device.current_package() != XHS_PACKAGE:
            time.sleep(2)
        log.info(f"当前前台:{device.current_package()}")

        goal = _build_goal(args.count, args.topic)
        log.info(f"开始 VLM 浏览(目标 {args.count} 条)")

        try:
            action_log = run_vlm_loop(
                device, goal,
                states=BROWSE_STATES,
                initial_state="FEED",
                max_steps=80,
            )
        except VLMLoopError as e:
            return SkillResult(
                ok=False,
                summary=f"浏览失败:{e}",
                artifacts=sorted(ctx.task_dir.glob("step_*.png")),
            )

        # 收集所有 report 动作
        reports: list[str] = []
        for a in action_log:
            if a.get("action") == "report":
                txt = (a.get("params") or {}).get("text", "").strip()
                if txt:
                    reports.append(txt)

        if not reports:
            return SkillResult(
                ok=False,
                summary="VLM 没用 report 上报任何内容,可能它把笔记内容写在 description 里了",
                artifacts=sorted(ctx.task_dir.glob("step_*.png")),
            )

        # 汇总
        body = "\n\n".join(f"{i + 1}. {r}" for i, r in enumerate(reports))
        summary = f"已读取 {len(reports)} 条小红书笔记:\n\n{body}"

        try:
            device.go_home()
        except Exception:
            pass

        return SkillResult(
            ok=True,
            summary=summary,
            artifacts=sorted(ctx.task_dir.glob("step_*.png")),
            extra={"reports": reports, "count_actual": len(reports)},
        )


SKILL = _BrowseXhsPosts()


def _cli() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=2)
    p.add_argument("--topic", default=None)
    ns = p.parse_args()

    skill_args = BrowseXhsArgs(count=ns.count, topic=ns.topic)
    task_id = uuid.uuid4().hex[:12]
    task_dir = cfg.RUNS_DIR / task_id
    from mobile_agent.utils.cancel import CancelToken
    from mobile_agent.utils.logger import get_logger

    cancel = CancelToken()
    logger = get_logger(f"task.{task_id}", task_dir=task_dir)
    device = Device(task_dir=task_dir, cancel_token=cancel)
    ctx = RunContext(
        device=device, task_id=task_id, task_dir=task_dir,
        cancel_token=cancel, logger=logger,
    )
    try:
        with device.session():
            result = SKILL.run(skill_args, ctx)
        print(f"\nOK={result.ok}\n")
        print(result.summary)
        print(f"\n截图:{len(result.artifacts)} 张 → {task_dir}")
    except Exception as e:
        logger.exception(f"失败:{e}")
        raise


if __name__ == "__main__":
    _cli()
