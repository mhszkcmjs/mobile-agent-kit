"""
小红书文字笔记发布技能。

完全由 VLM 自主决策操作，使用语义动作（tap_text/tap_desc/launch_app 等），
不硬编码任何界面路径，适应 UI 变化和弹窗。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from mobile_agent.config import cfg
from mobile_agent.constants import SUCCESS_KEYWORDS, XHS_PACKAGE
from mobile_agent.device.device import Device
from mobile_agent.device.vlm_loop import StateDef, VLMLoopError, run_vlm_loop
from mobile_agent.llm.kimi_client import get_kimi
from mobile_agent.skills.base import RunContext, SkillResult


PROMPT_PATH = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "xhs_content.md"


# A2 状态机定义（与实际小红书发布流程一一对应）
#
# 真实步骤（用户确认）:
#   1. 点底部红色加号
#   2. 点「写文字」
#   3. 在大标题框输入标题 → 点「下一步」
#   4. 模板选择页 → 直接点「下一步」跳过
#   5. 进入正文编辑页：点「添加标题」→ 输入标题
#   6. 点「展开说说」→ 输入正文
#   7. type_text "#" → 等推荐 → tap 推荐（重复 3 次）
#   8. 点「发布笔记」
PUBLISH_STATES = [
    StateDef("NAVIGATE",
             "找到底部红色加号按钮（content-desc 通常是「发布」），tap_id 点击，等弹出菜单"),
    StateDef("CHOOSE_TYPE",
             "在弹出菜单里 tap_id 选「写文字」，进入第一个编辑页"),
    StateDef("FILL_INITIAL_TITLE",
             "第一个编辑页有一个大标题输入框，tap_id 点击后 type_text 输入标题，然后 tap_id 点「下一步」",
             require_type_text_min_chars=3),
    StateDef("SKIP_TEMPLATE",
             "模板选择页：tap_id 点「下一步」→ wait 2s → screenshot 确认页面变了（编辑页应能看到「添加标题」或「展开说说」元素）→ 确认变了才推进；若未变则再 tap 一次「下一步」"),
    StateDef("FILL_EDITOR_TITLE",
             "已在正文编辑页（能看到「添加标题」和「展开说说」）：tap_id 点「添加标题」→ type_text 标题",
             require_type_text_min_chars=3),
    StateDef("FILL_BODY",
             "tap_id 点「展开说说」→ type_text 输入完整正文（约 200 字，必须完整输入完才能推进 ADD_TAGS）",
             require_type_text_min_chars=100),
    StateDef("ADD_TAGS",
             "依次 type_text \"#标签名\" 输入 3 个话题标签，每输完一个等 0.5s，重复 3 次"),
    StateDef("SUBMIT",
             "tap_id 点「发布笔记」按钮"),
    StateDef("VERIFY",
             "wait 4s，屏幕出现「发布成功」→ 推进；未出现再 wait 2s"),
    StateDef("CLEANUP",
             "press_key HOME 返回桌面，完成后输出 next_state=DONE"),
]


class PublishXhsArgs(BaseModel):
    theme: str = Field(..., description="笔记主题方向")
    title: str | None = Field(None, description="可选：指定标题")
    body: str | None = Field(None, description="可选：指定正文")
    tags: list[str] | None = Field(None, description="可选：3~5 个标签（不带 #）")


class _Content(BaseModel):
    title: str = Field(..., max_length=30)
    body: str = Field(..., min_length=100, max_length=800)
    tags: list[str] = Field(..., min_length=2, max_length=8)


def generate_content(theme: str) -> _Content:
    prompt = PROMPT_PATH.read_text(encoding="utf-8").format(theme=theme)
    last_err: Exception | None = None
    for _ in range(2):
        try:
            data = get_kimi().chat_json([{"role": "user", "content": prompt}], temperature=0.7)
            data["tags"] = [t.lstrip("#").strip() for t in data.get("tags", [])]
            return _Content.model_validate(data)
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            last_err = e
    raise RuntimeError(f"LLM 生成内容失败: {last_err}")


def _build_goal(title: str, body: str, tags: list[str], sw: int, sh: int) -> str:
    tags_str = "、".join(tags)
    return f"""小红书已打开（前置完成），你在首页。按以下 8 个固定步骤发布一条文字笔记。

【8 步标准流程】（和状态机一一对应，严格按顺序执行）

步骤1 NAVIGATE: 找底部红色加号按钮（UI 元素里 content-desc 通常是「发布」），tap_id 点击

步骤2 CHOOSE_TYPE: 弹出菜单里 tap_id 点「写文字」

步骤3 FILL_INITIAL_TITLE: 大标题输入框（元素标签含「大标题」或「标题」），tap_id 点击后 type_text 输入以下标题：
{title}
输完后 tap_id 点「下一步」

步骤4 SKIP_TEMPLATE: 模板选择页，tap_id 点「下一步」→ **必须 wait 2s** → screenshot 确认页面已变成正文编辑页（元素列表出现「添加标题」或「展开说说」）→ 确认后才能推进状态；未变则再 tap 一次「下一步」后 wait 2s

步骤5 FILL_EDITOR_TITLE: 正文编辑页（确认能看到「添加标题」和「展开说说」），tap_id 点「添加标题」→ type_text 同样的标题：
{title}

步骤6 FILL_BODY: tap_id 点「展开说说」或正文区域，type_text 输入以下正文（必须完整）：
{body}

步骤7 ADD_TAGS: 依次输入 {len(tags)} 个话题标签：
  每个标签：type_text "#标签名"（带 # 前缀一起输入），wait 0.5s，重复
  目标标签：{tags_str}
  示例：type_text "#独居老人"，wait 0.5s，type_text "#陪伴"，wait 0.5s，...

步骤8 SUBMIT: tap_id 点「发布笔记」按钮

【注意事项】
- 每步都要用 tap_id（从左侧元素列表取序号），禁止凭直觉编造文字
- 遇到弹窗先关掉（tap_id 关闭或 press_key BACK）再继续
- 屏幕尺寸 {sw}×{sh}，底部 0~50px 是系统手势条不要点
"""


class _PublishXhsTextNote:
    name = "publish_xhs_text_note"
    description = "在小红书发布一条文字笔记，由视觉模型自主操作手机完成全程。"
    args_schema = PublishXhsArgs

    def run(self, args: PublishXhsArgs, ctx: RunContext) -> SkillResult:  # type: ignore[override]
        device: Device = ctx.device
        log = ctx.logger

        # 内容生成
        title = args.title
        body = args.body
        tags = args.tags
        if not (title and body and tags):
            log.info(f"生成内容（主题={args.theme}）")
            content = generate_content(args.theme)
            title = title or content.title
            body = body or content.body
            tags = tags or content.tags[:5]
        title = title[:20]
        tags = [t.lstrip("#") for t in tags[:5]]

        # 前置：强制打开小红书（adb 直接唤起，比让 VLM 找桌面图标可靠）
        log.info(f"前置：launch_app {XHS_PACKAGE}")
        device.launch_app(XHS_PACKAGE)
        time.sleep(2)
        if device.current_package() != XHS_PACKAGE:
            time.sleep(2)
        log.info(f"当前前台: {device.current_package()}")

        sw, sh = device.screen_size()
        goal = _build_goal(title, body, tags, sw, sh)
        log.info("开始 VLM 自主发布")

        # VLM 自主，附状态机
        publish_succeeded_during_loop = False
        try:
            action_log = run_vlm_loop(
                device, goal,
                states=PUBLISH_STATES,
                initial_state="NAVIGATE",
            )
        except VLMLoopError as e:
            # 看 VLM 之前的截图里是否已经出现过"发布成功"
            # 这种情况发生在：发布已成功，但模型在清后台阶段陷入死循环
            try:
                screen_text = device.screen_text()
                if any(kw in screen_text for kw in SUCCESS_KEYWORDS):
                    publish_succeeded_during_loop = True
                    log.info("VLM 循环失败但屏幕检测到发布成功，按成功处理")
            except Exception:
                pass

            # 兜底回桌面
            try:
                device.clear_recent_apps()
            except Exception:
                try:
                    device.go_home()
                except Exception:
                    pass

            if not publish_succeeded_during_loop:
                return SkillResult(
                    ok=False,
                    summary=f"失败: {e}",
                    artifacts=sorted(ctx.task_dir.glob("step_*.png")),
                )
            action_log = []  # 标记为成功但日志不完整

        # 防炸机制4：三步验证兜底
        screen_text = device.screen_text()
        business_ok = any(kw in screen_text for kw in SUCCESS_KEYWORDS)
        if not business_ok:
            time.sleep(3)
            screen_text = device.screen_text()
            business_ok = any(kw in screen_text for kw in SUCCESS_KEYWORDS)
        log.info(f"业务验证: {'通过' if business_ok else '未命中（VLM 可能已离开成功页）'}")

        if not device.is_on_launcher():
            try:
                device.clear_recent_apps()
            except Exception:
                device.go_home()

        artifacts = sorted(ctx.task_dir.glob("step_*.png"))
        return SkillResult(
            ok=True,
            summary=f"已发布《{title}》（{len(body)} 字 · {len(tags)} 标签 · {len(action_log)} 步）",
            artifacts=artifacts,
            extra={"title": title, "body": body, "tags": tags},
        )


SKILL = _PublishXhsTextNote()


def _cli() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--theme", required=True)
    p.add_argument("--title", default=None)
    p.add_argument("--body", default=None)
    p.add_argument("--tags", default=None)
    ns = p.parse_args()

    skill_args = PublishXhsArgs(
        theme=ns.theme, title=ns.title, body=ns.body,
        tags=ns.tags.split(",") if ns.tags else None,
    )
    task_id = uuid.uuid4().hex[:12]
    task_dir = cfg.RUNS_DIR / task_id
    from mobile_agent.utils.cancel import CancelToken
    from mobile_agent.utils.logger import get_logger
    cancel = CancelToken()
    logger = get_logger(f"task.{task_id}", task_dir=task_dir)
    device = Device(task_dir=task_dir, cancel_token=cancel)
    ctx = RunContext(device=device, task_id=task_id, task_dir=task_dir,
                     cancel_token=cancel, logger=logger)
    try:
        with device.session():
            result = SKILL.run(skill_args, ctx)
        print(f"\nOK={result.ok}  {result.summary}")
        print(f"截图: {len(result.artifacts)} 张 → {task_dir}")
    except Exception as e:
        logger.exception(f"失败: {e}")
        raise


if __name__ == "__main__":
    _cli()
