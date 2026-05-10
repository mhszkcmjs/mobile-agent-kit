"""
手动 REPL —— 不走 Agent,直接调用 Device API 调试。

启动后会打印命令清单。常用:
  shot                        截图
  pkg                         当前包名
  home                        回桌面
  launch com.xingin.xhs       打开 App
  tap 540 1900                坐标点击
  find text=写文字            找元素并打印 bounds
  type 你好世界                输入中文
  swipe 540 1800 540 600      滑动
  recent                      清后台
  exit / Ctrl+D                退出
"""
from __future__ import annotations

import shlex
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mobile_agent.device.device import Device  # noqa: E402


HELP = __doc__


def parse_kv(args: list[str]) -> dict[str, str]:
    out = {}
    for a in args:
        if "=" in a:
            k, v = a.split("=", 1)
            out[k] = v
    return out


def main() -> None:
    print(HELP)
    print("=" * 50)
    d = Device()
    print(f"已连:{d.serial}  屏幕={d.screen_size()}")
    print()

    while True:
        try:
            line = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("exit", "quit", "q"):
            break

        try:
            tokens = shlex.split(line)
            cmd, *args = tokens
            if cmd == "help":
                print(HELP)
            elif cmd == "shot":
                p = d.screenshot(label=(args[0] if args else ""))
                print(f"saved: {p}")
            elif cmd == "pkg":
                print(d.current_package())
            elif cmd == "home":
                d.go_home()
            elif cmd == "launch" and args:
                d.launch_app(args[0])
                print(f"now: {d.current_package()}")
            elif cmd == "tap" and len(args) >= 2:
                d.tap(int(args[0]), int(args[1]))
            elif cmd == "swipe" and len(args) >= 4:
                dur = int(args[4]) if len(args) >= 5 else 300
                d.swipe(int(args[0]), int(args[1]), int(args[2]), int(args[3]), dur)
            elif cmd == "type" and args:
                d.type_text(" ".join(args))
            elif cmd == "press" and args:
                d.press_key(args[0].upper())  # type: ignore[arg-type]
            elif cmd == "find":
                kv = parse_kv(args)
                el = d.find(**kv)  # type: ignore[arg-type]
                print(el)
            elif cmd == "recent":
                d.clear_recent_apps()
            else:
                print(f"未知命令:{line}")
        except Exception:
            traceback.print_exc()

    print("bye")


if __name__ == "__main__":
    main()
