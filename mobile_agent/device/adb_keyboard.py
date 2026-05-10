"""
中文输入注入 —— 通过 ADBKeyboard 的广播协议。

ADBKeyboard 监听以下广播:
  - ADB_INPUT_TEXT  (Base64 编码的文字)
  - ADB_INPUT_CODE  (按键码)
  - ADB_CLEAR_TEXT  (清空当前输入框)

参考:https://github.com/senzhk/ADBKeyBoard
"""
from __future__ import annotations

import base64
import shlex
import subprocess

from mobile_agent.constants import ADB_KEYBOARD_IME, ADB_KEYBOARD_PACKAGE


class AdbKeyboardError(RuntimeError):
    pass


class AdbKeyboard:
    def __init__(self, serial: str) -> None:
        self.serial = serial

    # ── public ───────────────────────────────────────
    def is_installed(self) -> bool:
        out = self._adb("shell", "pm", "list", "packages", ADB_KEYBOARD_PACKAGE)
        return ADB_KEYBOARD_PACKAGE in out

    def is_current_ime(self) -> bool:
        out = self._adb("shell", "settings", "get", "secure", "default_input_method")
        return ADB_KEYBOARD_IME in out

    def set_as_default(self) -> None:
        if not self.is_installed():
            raise AdbKeyboardError(
                f"未装 {ADB_KEYBOARD_PACKAGE},先跑 install_adbkeyboard.ps1"
            )
        self._adb("shell", "ime", "enable", ADB_KEYBOARD_IME)
        self._adb("shell", "ime", "set", ADB_KEYBOARD_IME)

    def restore_default(self, original_ime: str | None) -> None:
        if not original_ime:
            return
        self._adb("shell", "ime", "set", original_ime)

    def get_current_ime(self) -> str:
        out = self._adb("shell", "settings", "get", "secure", "default_input_method")
        return out.strip()

    def type_text(self, text: str) -> None:
        """输入任意 Unicode 文字。"""
        if not text:
            return
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        # 注:--es 后跟 key value;value 不能含 shell 特殊字符,b64 本身只含 [A-Za-z0-9+/=]
        self._adb(
            "shell",
            "am", "broadcast",
            "-a", "ADB_INPUT_B64",
            "--es", "msg", b64,
        )

    def clear(self) -> None:
        """清空当前焦点的输入框。"""
        self._adb("shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT")

    # ── internals ────────────────────────────────────
    def _adb(self, *args: str) -> str:
        cmd = ["adb", "-s", self.serial, *args]
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15, check=False,
                encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            raise AdbKeyboardError(f"adb 超时:{shlex.join(cmd)}")
        if out.returncode != 0:
            raise AdbKeyboardError(
                f"adb 失败({out.returncode}):{shlex.join(cmd)}\n{out.stderr.strip()}"
            )
        return out.stdout
