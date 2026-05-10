"""
OCR 兜底封装。

PaddleOCR 在 Windows 上安装可能失败(需 VC++ 运行库),
所以采用 lazy import,导入失败时整个模块降级为不可用,Device.find 会跳过 OCR 这级。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mobile_agent.device.ui_tree import UIElement


class _OCRBackend:
    """统一接口:输入图片路径 → 输出 [(text, bbox), ...]。"""

    def detect(self, image_path: Path) -> list[tuple[str, tuple[int, int, int, int]]]:
        raise NotImplementedError


class _PaddleOCRBackend(_OCRBackend):
    def __init__(self) -> None:
        from paddleocr import PaddleOCR  # type: ignore

        self._impl = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)

    def detect(self, image_path: Path) -> list[tuple[str, tuple[int, int, int, int]]]:
        result = self._impl.ocr(str(image_path), cls=False)
        out: list[tuple[str, tuple[int, int, int, int]]] = []
        if not result or not result[0]:
            return out
        for line in result[0]:
            box, (text, _conf) = line
            xs = [int(p[0]) for p in box]
            ys = [int(p[1]) for p in box]
            out.append((text, (min(xs), min(ys), max(xs), max(ys))))
        return out


class _NoopOCR(_OCRBackend):
    def detect(self, image_path: Path) -> list[tuple[str, tuple[int, int, int, int]]]:
        return []


_backend: _OCRBackend | None = None
_unavailable_reason: str | None = None


def get_ocr() -> _OCRBackend:
    global _backend, _unavailable_reason
    if _backend is not None:
        return _backend
    try:
        _backend = _PaddleOCRBackend()
    except Exception as e:  # 装不上就降级
        _unavailable_reason = str(e)
        _backend = _NoopOCR()
    return _backend


def ocr_available() -> bool:
    return isinstance(get_ocr(), _PaddleOCRBackend)


def ocr_unavailable_reason() -> str | None:
    if ocr_available():
        return None
    return _unavailable_reason or "OCR 未启用(可装 paddleocr)"


def find_text_in_image(
    image_path: Path,
    needle: str,
    *,
    contains: bool = True,
) -> "UIElement | None":
    """OCR 找文字 → 返回一个伪 UIElement(只填 text 与 bounds)。"""
    from mobile_agent.device.ui_tree import UIElement  # 局部导入,避免循环

    matches = get_ocr().detect(image_path)
    for text, bounds in matches:
        if contains:
            if needle in text:
                return UIElement(text=text, bounds=bounds)
        else:
            if needle == text:
                return UIElement(text=text, bounds=bounds)
    return None
