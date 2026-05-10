"""
VLM 自主动作循环 —— 语义动作 + 状态机版。

核心改造:
  A1. SoM-lite —— 元素带序号 [#1] [#2]...,新主动作 tap_id 杜绝坐标估错
  A2. 任务状态机 —— 技能层定义有限状态,VLM 每步必须给 next_state,DONE 即退出

向后兼容:
  - states=None 时走无状态模式（同旧 vlm_loop）
  - 技能层若提供 states,VLM 在每步输出加 next_state 字段
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mobile_agent.constants import WAIT_AFTER_HASH_INPUT, XHS_PACKAGE
from mobile_agent.device.device import Device
from mobile_agent.llm.kimi_client import get_kimi
from mobile_agent.utils.logger import get_logger


_LOG = get_logger("vlm_loop")

MAX_STEPS = 60
REPEAT_LIMIT = 5

_APP_MAP = {
    "小红书": XHS_PACKAGE,
    "xhs": XHS_PACKAGE,
    "微信": "com.tencent.mm",
    "抖音": "com.ss.android.ugc.aweme",
}

# ── 状态机定义 ────────────────────────────────────────
@dataclass
class StateDef:
    name: str          # 简短状态名，全大写
    description: str   # 一句话描述这个状态做什么
    # 出场条件：进入本状态后,这些动作必须发生过才能推进到下一状态
    # （防止模型谎报状态完成）
    require_type_text_min_chars: int = 0  # 累计 type_text 字数下限


# ── System Prompt ─────────────────────────────────────
_SYSTEM_PROMPT_BASE = """你是一名操控安卓手机的 AI 助手。每轮你会收到：
1. 当前屏幕截图
2. 屏幕上的可点击元素列表（带序号 [#1] [#2]... 含文字标签和精确像素坐标）
{state_intro}

## 输出格式（严格）
只输出一个 JSON 对象，不含 markdown 代码块：
{{
  "thought": "分析当前屏幕，说明下一步意图",
  "action": "<动作>",
  "params": {{...}},{next_state_field}
  "description": "一句话描述本步操作"
}}

## 动作清单（按推荐度排序）
| 动作 | params | 说明 |
|------|--------|------|
| **tap_id**     | {{"id": int}}            | **首选**。从元素列表里挑一个序号点击。坐标由代码精确给出。 |
| tap_text       | {{"text": "标签文字"}}    | 当列表里有这个文字、但你忘了序号时用 |
| tap_coords     | {{"x": int, "y": int}}   | **最后兜底**。元素列表里完全没合适项时（如纯图标按钮）才用 |
| launch_app     | {{"name": "小红书"}}      | 直接唤起 App，比点桌面图标可靠 |
| type_text      | {{"text": "..."}}        | 向当前焦点输入框注入文字（支持中文）|
| swipe          | {{"direction": "up/down/left/right", "distance": "short/medium/long"}} | 滑动 |
| press_key      | {{"key": "HOME/BACK/RECENT/ENTER"}} | 系统键 |
| wait           | {{"seconds": 1.5}}       | 等动画/弹窗加载 |
| screenshot     | {{}}                     | 仅观察不动作 |
| report         | {{"text": "..."}}        | 阅读类任务上报有用信息到结果列表 |
| done           | {{}}                     | 任务完成 |
| failed         | {{"reason": "..."}}      | 无法继续 |

## 核心规则
1. **优先用 tap_id**。元素列表里给出了序号 + 标签 + 精确坐标，直接选序号最准。
2. tap_coords 是最后手段；必须先确认元素列表里没有合适项。
3. **不许编造列表里不存在的元素文字**。tap_text 的参数必须能在列表里找到。
4. 遇到弹窗先关掉（找列表里的关闭按钮 tap_id，或 press_key BACK）。
5. **tap_id 一个输入框后,下一步必须立刻 type_text 输入内容**——禁止连续 tap 同一个输入框！即使输入框显示占位文字（如"添加标题"/"展开说说"）也是已聚焦,直接输入即可。
6. 插入话题标签：直接 type_text "#标签名"（如 type_text "#独居老人"），wait 0.5s，再输下一个。
7. 看到"发布成功"或类似字样后再 done，不要提前。
8. 屏幕尺寸 {width}×{height}。底部 0~50px 是系统手势条，禁止点击。
{state_rules}"""

_STEP_PROMPT = """## 任务目标
{goal}
{current_state_block}
## 已执行历史（最近 {n} 步）
{history}

## 当前屏幕可操作元素
{ui_elements}

根据截图和元素列表，决定下一步。"""


def _build_system_prompt(width: int, height: int, states: list[StateDef] | None) -> str:
    if not states:
        return _SYSTEM_PROMPT_BASE.format(
            state_intro="",
            next_state_field="",
            state_rules="",
            width=width,
            height=height,
        )

    # 把 description 里的花括号转义，防止 format() 报 KeyError
    state_lines = "\n".join(
        f"  - {s.name}: {s.description.replace('{', '{{').replace('}', '}}')}"
        for s in states
    )
    state_intro = f"\n3. 当前任务的状态机（你必须沿着这些状态推进任务，绝不回头）:\n{state_lines}"
    next_state_field = '\n  "next_state": "<当前状态名 / 下一个状态名 / DONE>",'
    state_rules = (
        "\n9. **状态推进规则**：每步必须输出 next_state。当前阶段任务未完成时填当前状态名；"
        "完成进入下一阶段时填下一个状态名；整个任务全部完成时填 DONE。"
        "\n10. 状态只能向前推进，不要倒退到已经做完的状态。"
    )
    return _SYSTEM_PROMPT_BASE.format(
        state_intro=state_intro,
        next_state_field=next_state_field,
        state_rules=state_rules,
        width=width,
        height=height,
    )


# ── 元素表 ────────────────────────────────────────────
@dataclass
class _UIElem:
    idx: int
    label: str
    cx: int
    cy: int
    bounds: tuple[int, int, int, int]
    clickable: bool


# ── A3 屏幕全文 → 系统提示 关键词表 ────────────────────
_SCREEN_HINT_RULES: list[tuple[tuple[str, ...], str]] = [
    (("上传中", "发布中", "发送中", "正在上传", "正在发布"),
     "[系统校验] 屏幕显示「上传中」,服务器正在处理,建议 wait 3~4 秒"),
    (("发布成功", "已发布", "发布完成"),
     "[系统校验] 屏幕已出现「发布成功」标志,可以推进到 CLEANUP/DONE"),
    (("需要登录", "请登录", "立即登录"),
     "[系统校验] 屏幕要求登录,本任务无法继续,建议输出 failed"),
    (("网络异常", "网络错误", "请检查网络"),
     "[系统校验] 屏幕显示网络异常,建议 wait 3s 后重试或 failed"),
    (("添加标题", "展开说说"),
     "[系统校验] 屏幕已进入正文编辑页（检测到「添加标题」/「展开说说」元素），可以推进 FILL_EDITOR_TITLE 或 FILL_BODY"),
]


def _dump_clickable(
    device: Device, max_items: int = 60
) -> tuple[str, dict[int, _UIElem], list[str]]:
    """
    导出可点击/可读元素,顺便扫描屏幕全文给出系统提示。
    返回:
      - 给 VLM 看的元素列表文本(带 [#N] 序号)
      - {idx: _UIElem} 字典,供 tap_id 查表点击
      - screen_hints: 基于屏幕全文关键词的系统提示列表(A3 强校验)
    """
    try:
        xml_str = device._u2.dump_hierarchy(compressed=True)
    except Exception as e:
        return f"(UI 树获取失败: {e})", {}, []
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return "(UI 树解析失败)", {}, []

    bounds_re = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
    elems: dict[int, _UIElem] = {}
    lines: list[str] = []
    all_text_parts: list[str] = []

    def _walk(node: ET.Element) -> None:
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        if text:
            all_text_parts.append(text)
        if desc and desc != text:
            all_text_parts.append(desc)
        if len(elems) >= max_items:
            for child in node:
                _walk(child)
            return
        clickable = node.get("clickable", "false") == "true"
        bounds_raw = node.get("bounds", "")
        label = text or desc
        if bounds_raw and (clickable or label):
            m = bounds_re.match(bounds_raw)
            if m:
                x1, y1, x2, y2 = int(m[1]), int(m[2]), int(m[3]), int(m[4])
                if (x2 - x1) > 5 and (y2 - y1) > 5:
                    idx = len(elems) + 1
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    el = _UIElem(
                        idx=idx,
                        label=label or "(无标签)",
                        cx=cx, cy=cy,
                        bounds=(x1, y1, x2, y2),
                        clickable=clickable,
                    )
                    elems[idx] = el
                    flag = "可点" if clickable else "只读"
                    lines.append(
                        f'[#{idx:>2}] [{flag}] "{el.label}"  ({cx},{cy})'
                    )
        for child in node:
            _walk(child)

    _walk(root)
    text_repr = "\n".join(lines) if lines else "(无可操作元素)"

    full_text = " ".join(all_text_parts)
    screen_hints: list[str] = []
    for keywords, hint in _SCREEN_HINT_RULES:
        if any(kw in full_text for kw in keywords):
            screen_hints.append(hint)

    return text_repr, elems, screen_hints


# ── tap 兜底：UI 树找不到时让 VLM 看图定坐标 ──────────
def _vlm_coord_fallback(device: Device, hint: str) -> None:
    from mobile_agent.device.vlm_finder import find_by_vlm
    shot = device.screenshot(label="fallback")
    el = find_by_vlm(shot, hint)
    if el:
        _LOG.info(f"[VLM 兜底] '{hint}' → {el.center}")
        device.tap_element(el)
    else:
        _LOG.warning(f"[VLM 兜底] '{hint}' 也找不到，跳过本步")


# ── 主循环 ────────────────────────────────────────────
class VLMLoopError(RuntimeError):
    pass


# ── 页面变化检测（通用） ────────────────────────────────
def _ui_signature(elems: dict[int, _UIElem]) -> frozenset[str]:
    """把当前 UI 树的元素标签集合作为页面签名。"""
    return frozenset(el.label for el in elems.values() if el.label != "(无标签)")


def _page_changed(sig_before: frozenset[str], sig_after: frozenset[str]) -> bool:
    """
    判断页面是否发生了明显变化（Jaccard 相似度低于阈值）。
    签名为空时保守地认为"变了"（避免误报）。
    """
    if not sig_before or not sig_after:
        return True
    intersection = len(sig_before & sig_after)
    union = len(sig_before | sig_after)
    similarity = intersection / union if union else 1.0
    return similarity < 0.75  # 超过 75% 相同 → 认为没变


# 导航类关键词：点这些元素才可能引发页面跳转
_NAV_KEYWORDS = frozenset({
    "下一步", "发布", "发布笔记", "取消", "确定", "完成", "返回",
    "关闭", "退出", "写文字", "写笔记", "清除全部", "全部清除",
})


def _is_nav_action(action: str, params: dict, ui_elems: dict[int, "_UIElem"]) -> bool:
    """判断本次动作是否属于导航类（可能引发页面切换）。"""
    # 系统键全都算导航
    if action == "press_key":
        return True
    # launch_app 算导航
    if action == "launch_app":
        return True
    # tap 类：看被点元素的标签是否含导航关键词
    if action == "tap_id":
        el = ui_elems.get(int(params.get("id", -1)))
        if el:
            return any(kw in el.label for kw in _NAV_KEYWORDS)
        return False
    if action in ("tap_text", "tap_desc", "tap_coords"):
        text = str(params.get("text") or params.get("desc") or "")
        return any(kw in text for kw in _NAV_KEYWORDS)
    # 其余（type_text, wait, screenshot, swipe, report）都不算导航
    return False


def run_vlm_loop(
    device: Device,
    goal: str,
    *,
    states: list[StateDef] | None = None,
    initial_state: str | None = None,
    max_steps: int = MAX_STEPS,
) -> list[dict[str, Any]]:
    """
    运行 VLM 自主循环。

    若提供 states,则启用 A2 状态机模式:
      - VLM 每步必须输出 next_state
      - next_state == "DONE" 立即结束循环
      - 历史中显示状态变迁
    """
    sw, sh = device.screen_size()
    system_prompt = _build_system_prompt(sw, sh, states)
    history: list[str] = []
    action_log: list[dict[str, Any]] = []
    recent_sigs: list[str] = []

    valid_states = {s.name for s in states} if states else set()
    valid_states.add("DONE")
    state_by_name = {s.name: s for s in states} if states else {}
    current_state = initial_state or (states[0].name if states else None)
    last_action: str | None = None
    # 页面变化验证所需状态
    pre_action_sig: frozenset[str] = frozenset()
    state_before_act: str | None = None
    last_action_was_nav: bool = False
    # 防输入框反复点击：记录上一次 tap 的元素标签
    last_tap_label: str | None = None
    # 状态出场守卫：累计在当前状态里 type_text 的字数
    chars_typed_in_state: int = 0

    for step in range(1, max_steps + 1):
        device.cancel_token.raise_if_cancelled()

        shot = device.screenshot(label=f"vlm_{step:03d}")
        _LOG.info(f"[vlm {step}] 截图 → {shot.name}")

        ui_text, ui_elems, screen_hints = _dump_clickable(device)
        current_ui_sig = _ui_signature(ui_elems)

        # ── 防输入框反复点击 ────────────────────────────
        # 上一步已经 tap 过某个元素，且本步 UI 树里同名元素还在 → 提示模型应该 type_text
        if last_tap_label and last_action == "tap_id":
            same_label_still_present = any(
                el.label == last_tap_label for el in ui_elems.values()
            )
            if same_label_still_present:
                hint = (
                    f"[系统校验] 你上一步已经 tap 了「{last_tap_label}」"
                    f"，输入框应该已经聚焦。下一步必须 type_text 输入内容，"
                    f"不要再 tap 同一个元素！如果输入框还显示占位文字也无所谓，直接 type_text。"
                )
                if not history or history[-1] != hint:
                    history.append(hint)
                    _LOG.info(hint)

        # ── 通用页面变化验证 ────────────────────────────
        # 条件：上一步是导航动作 AND 声明了状态跳转 AND 屏幕没明显变化 → 撤销跳转
        if (states and state_before_act is not None
                and state_before_act != current_state   # 上一步确实跳转了
                and last_action_was_nav                 # 只对导航动作验证
                and pre_action_sig
                and not _page_changed(pre_action_sig, current_ui_sig)):
            # 屏幕没明显变化 → 撤销跳转，告知模型
            _LOG.warning(
                f"[页面验证] 屏幕未明显变化，撤销状态跳转 {current_state} → {state_before_act}"
            )
            current_state = state_before_act
            screen_hints.append(
                f"[系统校验] 上一步操作后屏幕无明显变化，疑似页面未跳转，"
                f"状态已回退至 {current_state}，请 wait 1s 后重试或确认操作是否生效"
            )

        # A3: 上一动作后的代码端校验,作为系统提示注入历史
        if last_action == "launch_app":
            try:
                cur_pkg = device.current_package()
                if cur_pkg:
                    history.append(f"[系统校验] launch_app 完成,当前前台 = {cur_pkg}")
            except Exception:
                pass
        for h in screen_hints:
            if not history or history[-1] != h:  # 去重
                history.append(h)
                _LOG.info(h)

        # 当前状态块
        current_state_block = ""
        if states and current_state:
            sd = next((s for s in states if s.name == current_state), None)
            sd_desc = sd.description if sd else ""
            current_state_block = f"\n## 当前状态\n→ {current_state}: {sd_desc}\n"

        history_str = "\n".join(f"- {h}" for h in history[-12:]) or "（无）"
        user_prompt = _STEP_PROMPT.format(
            goal=goal,
            current_state_block=current_state_block,
            n=min(len(history), 12),
            history=history_str,
            ui_elements=ui_text,
        )
        full_prompt = system_prompt + "\n\n" + user_prompt

        try:
            result = get_kimi().chat_json_with_image(full_prompt, shot, temperature=0.1)
        except Exception as e:
            _LOG.warning(f"[vlm {step}] 调用失败，2s 重试: {e}")
            time.sleep(2)
            result = get_kimi().chat_json_with_image(full_prompt, shot, temperature=0.1)

        action = result.get("action", "wait")
        params = result.get("params") or {}
        thought = result.get("thought", "")
        desc = result.get("description", action)
        next_state_raw = (result.get("next_state") or "").strip()

        # 状态推进
        next_state: str | None = None
        if states:
            if next_state_raw and next_state_raw in valid_states:
                next_state = next_state_raw
            else:
                if next_state_raw:
                    _LOG.warning(
                        f"[vlm {step}] next_state='{next_state_raw}' 非法，保持 {current_state}"
                    )
                next_state = current_state

        # 历史展示
        state_tag = ""
        if states and current_state:
            if next_state and next_state != current_state:
                state_tag = f"[{current_state}→{next_state}] "
            else:
                state_tag = f"[{current_state}] "
        _LOG.info(f"[vlm {step}] {state_tag}{action} {params} | {thought}")
        history.append(f"步骤{step} {state_tag}: {desc}")
        action_log.append({
            "step": step, "action": action, "params": params,
            "thought": thought, "screenshot": str(shot),
            "state": current_state, "next_state": next_state,
        })

        # 重复检测（同状态 + 同 action + 同 params）
        sig = f"{current_state}:{action}:{json.dumps(params, sort_keys=True, ensure_ascii=False)[:60]}"
        recent_sigs.append(sig)
        if len(recent_sigs) > REPEAT_LIMIT:
            recent_sigs.pop(0)
        if len(recent_sigs) == REPEAT_LIMIT and len(set(recent_sigs)) == 1:
            raise VLMLoopError(f"死循环：连续 {REPEAT_LIMIT} 步 [{current_state}] {action} {params}")

        # 终止条件
        if action == "done" or next_state == "DONE":
            _LOG.info(f"[vlm] 完成（共 {step} 步）")
            return action_log
        if action == "failed":
            raise VLMLoopError(f"模型失败: {params.get('reason', '?')}")

        # 记录动作执行前的签名和状态（供下一轮验证用）
        pre_action_sig = current_ui_sig
        state_before_act = current_state
        last_action_was_nav = _is_nav_action(action, params, ui_elems)

        # 记录 tap 的目标元素（防输入框反复点击）
        if action == "tap_id":
            el = ui_elems.get(int(params.get("id", -1)))
            last_tap_label = el.label if el else None
        elif action == "type_text":
            last_tap_label = None
            chars_typed_in_state += len(str(params.get("text", "")))

        _execute(device, action, params, ui_elems)
        last_action = action

        # ── 状态出场守卫 ───────────────────────────────
        if states and next_state and next_state != current_state:
            cur_def = state_by_name.get(current_state or "")
            min_chars = cur_def.require_type_text_min_chars if cur_def else 0
            if min_chars > 0 and chars_typed_in_state < min_chars:
                # 不放行,要求继续打字
                history.append(
                    f"[系统校验] {current_state} 状态要求至少输入 {min_chars} 字才能推进,"
                    f"目前才输入 {chars_typed_in_state} 字。请继续 type_text 输入剩余内容,"
                    f"不要急着推进 {next_state}。"
                )
                _LOG.warning(
                    f"[出场守卫] {current_state} 字数不足({chars_typed_in_state}/{min_chars}),"
                    f"驳回到 {next_state} 的跳转"
                )
            else:
                current_state = next_state
                chars_typed_in_state = 0  # 进新状态清零
                _LOG.info(f"[状态跳转] → {next_state}")

    raise VLMLoopError(f"超过最大步数 {max_steps}")


def _execute(
    device: Device,
    action: str,
    params: dict,
    ui_elems: dict[int, _UIElem],
) -> None:
    if action == "tap_id":
        try:
            idx = int(params.get("id", -1))
        except (TypeError, ValueError):
            _LOG.warning(f"tap_id: 非法 id={params}")
            return
        el = ui_elems.get(idx)
        if el is None:
            _LOG.warning(f"tap_id: id={idx} 不在元素列表中（最大 {len(ui_elems)}）")
            return
        _LOG.info(f"tap_id #{idx} '{el.label}' @ ({el.cx},{el.cy})")
        device.tap(el.cx, el.cy)

    elif action == "tap_text":
        text = str(params.get("text", ""))
        # 优先在当前 ui_elems 里精确/包含匹配（不再去 find()，省一次 dump）
        for el in ui_elems.values():
            if el.label == text:
                _LOG.info(f"tap_text 精准命中 '{text}' @ ({el.cx},{el.cy})")
                device.tap(el.cx, el.cy)
                return
        for el in ui_elems.values():
            if text and text in el.label:
                _LOG.info(f"tap_text 包含命中 '{text}' (实际'{el.label}') @ ({el.cx},{el.cy})")
                device.tap(el.cx, el.cy)
                return
        # 退到 device.find（含 OCR/VLM 多级兜底）
        ulel = device.find(text=text) or device.find(text_contains=text)
        if ulel:
            device.tap_element(ulel)
        else:
            _LOG.warning(f"tap_text: 元素列表+UI树都没找到 '{text}'，转 VLM 兜底")
            _vlm_coord_fallback(device, f"文字内容是「{text}」的可点击元素")

    elif action == "tap_desc":
        desc = str(params.get("desc", ""))
        el = device.find(content_desc=desc) or device.find(text_contains=desc)
        if el:
            device.tap_element(el)
        else:
            _LOG.warning(f"tap_desc: 没找到 '{desc}'，转 VLM 兜底")
            _vlm_coord_fallback(device, desc)

    elif action == "tap_coords":
        device.tap(int(params["x"]), int(params["y"]))

    elif action == "launch_app":
        name = str(params.get("name", ""))
        pkg = _APP_MAP.get(name) or params.get("package", "")
        if not pkg:
            _LOG.warning(f"launch_app: 未知 App '{name}'")
            return
        device.launch_app(pkg)

    elif action == "type_text":
        text = str(params.get("text", ""))
        device.type_text(text)
        if text.strip() == "#":
            time.sleep(WAIT_AFTER_HASH_INPUT)

    elif action == "swipe":
        sw, sh = device.screen_size()
        cx, cy = sw // 2, sh // 2
        dist_map = {"short": 200, "medium": 500, "long": 900}
        dist = dist_map.get(str(params.get("distance", "medium")), 500)
        direction = str(params.get("direction", "up"))
        if direction == "up":
            device.swipe(cx, cy + dist // 2, cx, cy - dist // 2)
        elif direction == "down":
            device.swipe(cx, cy - dist // 2, cx, cy + dist // 2)
        elif direction == "left":
            device.swipe(cx + dist // 2, cy, cx - dist // 2, cy)
        elif direction == "right":
            device.swipe(cx - dist // 2, cy, cx + dist // 2, cy)

    elif action == "press_key":
        device.press_key(str(params.get("key", "BACK")).upper())  # type: ignore[arg-type]

    elif action == "wait":
        device.wait(float(params.get("seconds", 1.0)))

    elif action == "screenshot":
        pass

    elif action == "report":
        text = str(params.get("text", ""))[:500]
        _LOG.info(f"[REPORT] {text}")

    else:
        _LOG.warning(f"未知 action={action!r}，跳过")
