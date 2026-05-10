"""
M0 设备自检:
  1. adb 在 PATH
  2. adb devices 至少有一台 device(非 unauthorized)
  3. uiautomator2 能连上 / 截图
  4. ADBKeyboard 已安装 + 已启用 IME
  5. 当前前台包名可读

跑通后再进 M1。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mobile_agent.config import cfg  # noqa: E402
from mobile_agent.constants import ADB_KEYBOARD_IME, ADB_KEYBOARD_PACKAGE  # noqa: E402


GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}[ OK ]{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"{RED}[FAIL]{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def step_adb_in_path() -> bool:
    if shutil.which("adb"):
        out = subprocess.run(["adb", "version"], capture_output=True, text=True).stdout
        ok(f"adb 在 PATH:{out.splitlines()[0]}")
        return True
    fail("adb 不在 PATH。装 platform-tools 并加 Path。")
    return False


def step_adb_devices() -> str | None:
    out = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout
    lines = [ln.strip() for ln in out.splitlines() if ln.strip() and "List of devices" not in ln]
    if not lines:
        fail("adb devices 没看到设备。检查 USB 线/驱动/调试授权。")
        return None
    serial, status = lines[0].split()[:2]
    if status != "device":
        fail(f"设备状态={status}(期望 device)。手机弹窗未授权或驱动缺。")
        return None
    if cfg.ANDROID_SERIAL and serial != cfg.ANDROID_SERIAL:
        warn(f".env 指定 {cfg.ANDROID_SERIAL},但实际看到 {serial},以实际为准")
    ok(f"设备:{serial}")
    return serial


def step_uiautomator2(serial: str) -> bool:
    try:
        import uiautomator2 as u2
    except ImportError:
        fail("缺 uiautomator2。pip install -r requirements.txt")
        return False
    try:
        d = u2.connect(serial)
        info = d.info
        ok(f"uiautomator2 已连:{info.get('productName')} / Android {info.get('sdkInt')}")
        # u2 3.x screenshot() 返回 PIL.Image,存文件再量大小
        import tempfile, os as _os
        tmp = tempfile.mktemp(suffix=".png")
        d.screenshot(tmp)
        size_kb = _os.path.getsize(tmp) // 1024
        _os.unlink(tmp)
        ok(f"截图成功(~{size_kb}KB)")
        return True
    except Exception as e:
        fail(f"uiautomator2 连接失败:{e}")
        warn("先跑 `python -m uiautomator2 init`")
        return False


def step_adbkeyboard(serial: str) -> bool:
    out = subprocess.run(
        ["adb", "-s", serial, "shell", "pm", "list", "packages", ADB_KEYBOARD_PACKAGE],
        capture_output=True, text=True,
    ).stdout
    if ADB_KEYBOARD_PACKAGE not in out:
        fail(f"未装 {ADB_KEYBOARD_PACKAGE}。跑 .\\scripts\\install_adbkeyboard.ps1")
        return False
    ok(f"ADBKeyboard 已装:{ADB_KEYBOARD_PACKAGE}")

    out2 = subprocess.run(
        ["adb", "-s", serial, "shell", "ime", "list", "-s"],
        capture_output=True, text=True,
    ).stdout
    if ADB_KEYBOARD_IME not in out2:
        warn(
            f"ADBKeyboard 未启用为 IME。手机【设置→语言和输入法→管理键盘】启用 ADBKeyboard"
        )
        return False
    ok(f"ADBKeyboard 已启用为 IME")
    return True


def step_current_package(serial: str) -> bool:
    out = subprocess.run(
        [
            "adb", "-s", serial, "shell",
            "dumpsys", "window", "windows",
        ],
        capture_output=True, text=True,
    ).stdout
    # 抓 mCurrentFocus 行
    pkg = None
    for ln in out.splitlines():
        if "mCurrentFocus" in ln and "/" in ln:
            try:
                pkg = ln.split()[-1].split("/")[0]
                break
            except Exception:
                pass
    if pkg:
        ok(f"前台包名:{pkg}")
        return True
    warn("读不到前台包名(可能锁屏中)")
    return False


def main() -> int:
    print("=== Mobile Agent 环境自检 ===\n")
    if not step_adb_in_path():
        return 1
    serial = step_adb_devices()
    if not serial:
        return 1
    if not step_uiautomator2(serial):
        return 1
    step_adbkeyboard(serial)        # 不强制 fail,允许后续手动启用
    step_current_package(serial)
    print("\n=== 自检完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
