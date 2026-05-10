"""
VLM 兜底找元素:把截图丢给 Kimi 视觉,让它返回元素中心坐标。

提示词强制 JSON 输出 {x, y} 或 {found: false}。
返回的坐标 + 一个 32x32 的虚拟 bounds 包成 UIElement。
"""
from __future__ import annotations

import json
from pathlib import Path

from mobile_agent.device.ui_tree import UIElement
from mobile_agent.llm.kimi_client import get_kimi


_PROMPT = """你是 UI 元素定位助手。我会给你一张安卓手机截图,以及对元素的自然语言描述。

任务:在截图中找到该元素,返回其中心点的像素坐标(以截图左上角为 (0,0))。

⚠️ 严格要求:
1. 只输出一个 JSON 对象,不要任何解释或 markdown 代码块。
2. 找到 → {{"found": true, "x": <int>, "y": <int>}}
3. 找不到 → {{"found": false}}
4. 不要猜测;模糊或不可见时一律 found=false。

元素描述:{hint}
"""


def find_by_vlm(image_path: Path, hint: str) -> UIElement | None:
    """让视觉模型在截图里定位 hint 描述的元素。"""
    raw = get_kimi().chat_with_image(_PROMPT.format(hint=hint), image_path, temperature=0)
    raw = raw.strip()
    # 容错:模型偶尔包 ```json
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not data.get("found"):
        return None
    try:
        x = int(data["x"])
        y = int(data["y"])
    except (KeyError, TypeError, ValueError):
        return None
    half = 16
    return UIElement(
        text=f"<vlm:{hint}>",
        bounds=(x - half, y - half, x + half, y + half),
    )
