"""
uiautomator2 selector wrapper + UIElement 数据结构。

UIElement 把 uiautomator2 dump 出的 XML 节点统一成一个简单 dataclass,
方便 Device 层与 Skill 层使用,不暴露 u2 的 selector 细节给上层。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UIElement:
    text: str = ""
    resource_id: str = ""
    content_desc: str = ""
    class_name: str = ""
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)  # (x1, y1, x2, y2)
    package: str = ""
    clickable: bool = False
    enabled: bool = True
    raw: dict[str, Any] = field(default_factory=dict)  # 原始 attrs 备查

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]

    def __repr__(self) -> str:
        return (
            f"UIElement(text={self.text!r}, id={self.resource_id!r}, "
            f"desc={self.content_desc!r}, bounds={self.bounds})"
        )


def from_u2_info(info: dict[str, Any]) -> UIElement:
    """uiautomator2 的 .info / .child().info 字典 → UIElement。"""
    b = info.get("bounds") or {}
    bounds = (
        b.get("left", 0),
        b.get("top", 0),
        b.get("right", 0),
        b.get("bottom", 0),
    )
    return UIElement(
        text=info.get("text") or "",
        resource_id=info.get("resourceName") or "",
        content_desc=info.get("contentDescription") or "",
        class_name=info.get("className") or "",
        bounds=bounds,
        package=info.get("packageName") or "",
        clickable=bool(info.get("clickable")),
        enabled=bool(info.get("enabled", True)),
        raw=info,
    )
