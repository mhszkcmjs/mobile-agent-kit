"""
Device 主类 —— L2 动作层。

职责:
  - 提供 PRD §6.1 的 12 个稳定接口
  - 强制等待表(§6.3)、tap 随机延迟、cancel 检查在这层落地
  - find 的三级查找(UI 树 → OCR → VLM)
  - 截图自动按步骤序号落盘到 task_dir
  - 不做业务判断,不调 LLM(VLM 兜底除外)

所有公开方法在执行前调用 _check_cancel,使用户取消能在 5s 内停下。
"""
from __future__ import annotations

import random
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Literal

import uiautomator2 as u2

from mobile_agent.config import cfg
from mobile_agent.constants import (
    LAUNCHER_WHITELIST,
    TAP_DELAY_MAX_MS,
    TAP_DELAY_MIN_MS,
    WAIT_AFTER_PAGE_CHANGE,
    WAIT_AFTER_PUBLISH_TAP,
    WAIT_AFTER_SWIPE,
    WAIT_AFTER_TAP,
    WAIT_AFTER_TYPE,
    FIND_RETRY_WAIT_SEC,
)
from mobile_agent.device.adb_keyboard import AdbKeyboard
from mobile_agent.device.ui_tree import UIElement, from_u2_info
from mobile_agent.utils.cancel import CancelToken
from mobile_agent.utils.logger import get_logger


KeyName = Literal["HOME", "BACK", "RECENT", "ENTER"]
PositionName = Literal["bottom_center", "bottom_left", "bottom_right", "top_center", "center"]


_KEY_MAP = {
    "HOME": "home",
    "BACK": "back",
    "RECENT": "recent",
    "ENTER": "enter",
}


class DeviceError(RuntimeError):
    pass


class Device:
    def __init__(
        self,
        serial: str | None = None,
        *,
        task_dir: Path | None = None,
        cancel_token: CancelToken | None = None,
    ) -> None:
        self.serial = serial or cfg.ANDROID_SERIAL or _autodetect_serial()
        self.task_dir = task_dir or (cfg.RUNS_DIR / f"adhoc-{uuid.uuid4().hex[:8]}")
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.cancel_token = cancel_token or CancelToken()
        self.log = get_logger("device", task_dir=self.task_dir)

        self.log.info(f"connect uiautomator2 → {self.serial}")
        self._u2: u2.Device = u2.connect(self.serial)
        self._step_no = 0
        self._screen_size: tuple[int, int] | None = None
        self._adb_keyboard: AdbKeyboard | None = None
        self._original_ime: str | None = None

    # ─────────────────────────────────────────────
    #  截图
    # ─────────────────────────────────────────────
    def screenshot(self, label: str = "") -> Path:
        self._check_cancel()
        self._step_no += 1
        suffix = f"_{label}" if label else ""
        path = self.task_dir / f"step_{self._step_no:03d}{suffix}.png"
        self._u2.screenshot(str(path))
        self.log.debug(f"screenshot → {path.name}")
        return path

    # ─────────────────────────────────────────────
    #  UI 树
    # ─────────────────────────────────────────────
    def dump_ui(self) -> list[UIElement]:
        """扫描整个可见 UI 树,返回扁平节点列表。"""
        self._check_cancel()
        nodes: list[UIElement] = []

        def _walk(elem) -> None:
            try:
                info = elem.info
                nodes.append(from_u2_info(info))
            except Exception:
                pass
            for child in elem.child():
                _walk(child)

        try:
            for child in self._u2(className="*").child():
                _walk(child)
        except Exception:
            # fallback:用 dump_hierarchy 的简单方式获取一个根 selector
            pass

        # 上面的 walk 在某些 ROM 上不稳;直接用 dump_hierarchy + xpath 查所有节点
        # 这里返回一个最小可用集即可 —— Skill 层用 find() 而不是 dump_ui()
        return nodes

    # ─────────────────────────────────────────────
    #  查找(三级)
    # ─────────────────────────────────────────────
    def find(
        self,
        *,
        text: str | None = None,
        resource_id: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        text_contains: str | None = None,
        position: PositionName | None = None,
        vlm_hint: str | None = None,
        screenshot: Path | None = None,
    ) -> UIElement | None:
        """三级查找:UI 树 → OCR → VLM。每升级前等待 1.5s 重新截图。"""
        self._check_cancel()

        # 第一级:UI 树精确匹配
        el = self._find_in_ui_tree(
            text=text,
            resource_id=resource_id,
            content_desc=content_desc,
            class_name=class_name,
            text_contains=text_contains,
        )
        if el is not None:
            el = self._filter_by_position(el, position)
            if el is not None:
                self.log.debug(f"find → ui_tree: {el}")
                return el

        # 第二级:OCR
        if text or text_contains:
            time.sleep(FIND_RETRY_WAIT_SEC)
            shot = screenshot or self.screenshot(label="for_ocr")
            try:
                from mobile_agent.device.ocr import find_text_in_image
                ocr_el = find_text_in_image(
                    shot, text or text_contains or "", contains=bool(text_contains)
                )
                if ocr_el is not None:
                    self.log.debug(f"find → ocr: {ocr_el}")
                    return ocr_el
            except Exception as e:
                self.log.debug(f"OCR 异常忽略:{e}")

        # 第三级:VLM
        if vlm_hint:
            time.sleep(FIND_RETRY_WAIT_SEC)
            shot = self.screenshot(label="for_vlm")
            try:
                from mobile_agent.device.vlm_finder import find_by_vlm
                vlm_el = find_by_vlm(shot, vlm_hint)
                if vlm_el is not None:
                    self.log.debug(f"find → vlm: {vlm_el}")
                    return vlm_el
            except Exception as e:
                self.log.warning(f"VLM 兜底失败:{e}")

        self.log.debug(
            f"find 全部失败 text={text!r} id={resource_id!r} desc={content_desc!r}"
        )
        return None

    def _find_in_ui_tree(
        self,
        *,
        text: str | None = None,
        resource_id: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        text_contains: str | None = None,
    ) -> UIElement | None:
        kwargs: dict = {}
        if text:
            kwargs["text"] = text
        if resource_id:
            kwargs["resourceId"] = resource_id
        if content_desc:
            kwargs["description"] = content_desc
        if class_name:
            kwargs["className"] = class_name
        if text_contains:
            kwargs["textContains"] = text_contains
        if not kwargs:
            return None
        try:
            sel = self._u2(**kwargs)
            if sel.exists(timeout=0.5):
                return from_u2_info(sel.info)
        except Exception:
            pass
        return None

    def _filter_by_position(
        self, el: UIElement, position: PositionName | None
    ) -> UIElement | None:
        """以屏幕大致区域过滤(MVP 简化:只拒绝明显不在该区域的元素)。"""
        if position is None:
            return el
        sw, sh = self.screen_size()
        cx, cy = el.center
        if position == "bottom_center":
            if cy < sh * 0.6:
                return None
            if not (sw * 0.3 <= cx <= sw * 0.7):
                return None
        elif position == "bottom_left":
            if cy < sh * 0.6 or cx > sw * 0.4:
                return None
        elif position == "bottom_right":
            if cy < sh * 0.6 or cx < sw * 0.6:
                return None
        elif position == "top_center":
            if cy > sh * 0.4 or not (sw * 0.3 <= cx <= sw * 0.7):
                return None
        elif position == "center":
            if not (sw * 0.3 <= cx <= sw * 0.7 and sh * 0.3 <= cy <= sh * 0.7):
                return None
        return el

    # ─────────────────────────────────────────────
    #  动作
    # ─────────────────────────────────────────────
    def tap(self, x: int, y: int) -> None:
        self._check_cancel()
        delay = random.randint(TAP_DELAY_MIN_MS, TAP_DELAY_MAX_MS) / 1000
        time.sleep(delay)
        self._u2.click(x, y)
        time.sleep(WAIT_AFTER_TAP)

    def tap_element(self, el: UIElement) -> None:
        x, y = el.center
        self.log.info(f"tap {el.text or el.content_desc or el.resource_id} @ ({x},{y})")
        self.tap(x, y)

    def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> None:
        self._check_cancel()
        self._u2.swipe(x1, y1, x2, y2, duration=duration_ms / 1000)
        time.sleep(WAIT_AFTER_SWIPE)

    def type_text(self, text: str) -> None:
        """注入文字(含中文)。优先用 u2 FastInputIME,降级用 ADBKeyboard。"""
        self._check_cancel()
        if not text:
            return
        try:
            self._u2.set_fastinput_ime(True)
            self._u2.send_keys(text)
        except Exception as e:
            self.log.warning(f"FastInputIME 失败({e}),降级 ADBKeyboard")
            self._ensure_adb_keyboard_active()
            assert self._adb_keyboard is not None
            self._adb_keyboard.type_text(text)
        time.sleep(WAIT_AFTER_TYPE)

    def clear_input(self) -> None:
        self._check_cancel()
        try:
            self._u2.set_fastinput_ime(True)
            self._u2.clear_text()
        except Exception:
            self._u2.press("ctrl+a")
            self._u2.press("delete")
        time.sleep(WAIT_AFTER_TYPE)

    def press_key(self, key: KeyName) -> None:
        self._check_cancel()
        u2_key = _KEY_MAP[key]
        self._u2.press(u2_key)
        time.sleep(WAIT_AFTER_TAP)

    # ─────────────────────────────────────────────
    #  观察
    # ─────────────────────────────────────────────
    def current_package(self) -> str:
        self._check_cancel()
        try:
            return self._u2.app_current().get("package", "") or ""
        except Exception:
            return ""

    def is_on_launcher(self) -> bool:
        return self.current_package() in LAUNCHER_WHITELIST

    def screen_size(self) -> tuple[int, int]:
        if self._screen_size is None:
            info = self._u2.info
            w = int(info.get("displayWidth") or 0)
            h = int(info.get("displayHeight") or 0)
            if not w or not h:
                w, h = self._u2.window_size()
            self._screen_size = (w, h)
        return self._screen_size

    def screen_text(self) -> str:
        """截图 + OCR → 返回拼成一行的文本(用于 SUCCESS_KEYWORDS 判定)。"""
        from mobile_agent.device.ocr import get_ocr, ocr_available
        if not ocr_available():
            # 退化:从 UI 树 dump 文本
            try:
                xml = self._u2.dump_hierarchy()
                return xml
            except Exception:
                return ""
        shot = self.screenshot(label="screen_text")
        return " ".join(t for t, _ in get_ocr().detect(shot))

    # ─────────────────────────────────────────────
    #  应用 / 桌面
    # ─────────────────────────────────────────────
    def launch_app(self, package: str) -> None:
        self._check_cancel()
        self.log.info(f"launch_app {package}")
        self._u2.app_start(package, stop=True)
        time.sleep(WAIT_AFTER_PAGE_CHANGE)

    def go_home(self) -> None:
        self.press_key("HOME")
        time.sleep(WAIT_AFTER_PAGE_CHANGE)

    def clear_recent_apps(self) -> None:
        """PRD §6.4 写死流程。"""
        self._check_cancel()
        self.log.info("clear_recent_apps")
        sw, sh = self.screen_size()

        # 1. 进多任务
        self.press_key("RECENT")
        time.sleep(1.5)
        self.screenshot(label="recent_open")

        # 2. 某些 ROM 多任务页要左滑出"清除全部"按钮
        self.swipe(int(sw * 0.2), int(sh * 0.5), int(sw * 0.8), int(sh * 0.5), 400)
        time.sleep(0.5)

        # 3. 找"清除全部" / "全部清除" / "Clear all"
        clear_btn = None
        for kw in ("全部清除", "清除全部", "Clear all", "清空", "一键清理"):
            clear_btn = self.find(text=kw) or self.find(text_contains=kw)
            if clear_btn:
                break
        if clear_btn is not None:
            self.tap_element(clear_btn)
            time.sleep(1.0)
        else:
            # 兜底:屏幕中下方推测一个"清除全部"位置
            self.log.warning("找不到清除全部按钮,fallback 点屏幕中下")
            self.tap(sw // 2, int(sh * 0.85))
            time.sleep(1.0)

        # 4. 回桌面
        self.press_key("HOME")
        time.sleep(WAIT_AFTER_PAGE_CHANGE)

        if not self.is_on_launcher():
            # 再来一次
            self.press_key("HOME")
            time.sleep(1.0)
        if not self.is_on_launcher():
            raise DeviceError(f"清后台后未回到桌面,当前包={self.current_package()}")

    # ─────────────────────────────────────────────
    #  输入法生命周期
    # ─────────────────────────────────────────────
    def _ensure_adb_keyboard_active(self) -> None:
        """仅在 FastInputIME 失败后才调用。ADBKeyboard 可选。"""
        if self._adb_keyboard is None:
            self._adb_keyboard = AdbKeyboard(self.serial)
            if not self._adb_keyboard.is_installed():
                raise DeviceError(
                    "FastInputIME 和 ADBKeyboard 均不可用,无法输入中文。"
                    "尝试 `python -m uiautomator2 init` 重装 FastInputIME。"
                )
            current = self._adb_keyboard.get_current_ime()
            if not current.endswith("AdbIME"):
                self._original_ime = current
                self._adb_keyboard.set_as_default()

    def restore_ime(self) -> None:
        """任务结束后恢复输入法(FastInputIME 模式下 u2 自动恢复,手动 set_fastinput_ime False)。"""
        try:
            self._u2.set_fastinput_ime(False)
        except Exception:
            pass
        if self._adb_keyboard and self._original_ime:
            try:
                self._adb_keyboard.restore_default(self._original_ime)
            except Exception as e:
                self.log.warning(f"恢复原输入法失败(忽略):{e}")
            self._original_ime = None

    # ─────────────────────────────────────────────
    #  内部
    # ─────────────────────────────────────────────
    def _check_cancel(self) -> None:
        self.cancel_token.raise_if_cancelled()

    def wait(self, seconds: float, label: str = "") -> None:
        """显式等待,期间仍响应 cancel(分片轮询)。"""
        end = time.time() + seconds
        while time.time() < end:
            self._check_cancel()
            time.sleep(min(0.2, end - time.time()))
        if label:
            self.log.debug(f"wait {seconds}s ({label})")

    @contextmanager
    def session(self):
        """用 with 包装,退出时自动回桌面 + 恢复 IME。失败时尽力清理。"""
        try:
            yield self
        finally:
            try:
                self.go_home()
            except Exception:
                pass
            self.restore_ime()


def _autodetect_serial() -> str:
    out = subprocess.run(
        ["adb", "devices"], capture_output=True, text=True, check=False
    ).stdout
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln or "List of devices" in ln:
            continue
        parts = ln.split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]
    raise DeviceError("找不到任何 USB 设备(adb devices)")


def make_default_device(
    *,
    task_dir: Path | None = None,
    cancel_token: CancelToken | None = None,
) -> Device:
    return Device(task_dir=task_dir, cancel_token=cancel_token)


# 这俩是为了类型检查给 IDE 的提示,运行时无影响
_ = Iterable
