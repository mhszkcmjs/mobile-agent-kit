"""
M0 必跑:确认 Kimi 模型 ID 与视觉支持。

依次试候选模型,记录:
  - 文本调用是否通
  - 视觉调用是否通(给一张本地小图)

跑完后把可用模型 ID 写回 .env 的 MODEL_NAME / VISION_MODEL_NAME。
"""
from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

# 允许从项目根直接 `python scripts/verify_kimi_model.py`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from mobile_agent.config import cfg  # noqa: E402

try:
    from openai import OpenAI
except ImportError:
    print("缺少 openai 包,先 pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


# 候选清单(PRD §3.1)。M0 第一件事就是确认哪些真实存在。
TEXT_CANDIDATES = [
    "kimi-latest",
    "kimi-k2-0711-preview",
    "moonshot-v1-8k",
    "moonshot-v1-32k",
    "moonshot-v1-128k",
    "kimi-m2.6",
]

VISION_CANDIDATES = [
    "moonshot-v1-32k-vision-preview",
    "moonshot-v1-128k-vision-preview",
    "moonshot-v1-8k-vision-preview",
    "kimi-latest",
]


def _make_test_image_b64() -> str:
    img = Image.new("RGB", (64, 64), color=(40, 80, 160))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _client() -> OpenAI:
    cfg.assert_llm_ready()
    return OpenAI(api_key=cfg.MOONSHOT_API_KEY, base_url=cfg.MOONSHOT_BASE_URL)


def try_text(client: OpenAI, model: str) -> tuple[bool, str]:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "回复仅一个字:好"}],
            temperature=0,
            timeout=30,
        )
        return True, (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return False, str(e)[:200]


def try_vision(client: OpenAI, model: str) -> tuple[bool, str]:
    img_b64 = _make_test_image_b64()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "图里主色是什么颜色?一个词回答。"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                        },
                    ],
                }
            ],
            temperature=0,
            timeout=30,
        )
        return True, (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return False, str(e)[:200]


def main() -> None:
    client = _client()
    print(f"endpoint = {cfg.MOONSHOT_BASE_URL}")
    print(f"key      = ...{cfg.MOONSHOT_API_KEY[-6:]}")
    print()

    print("=== 文本模型 ===")
    text_ok: list[str] = []
    for m in TEXT_CANDIDATES:
        ok, msg = try_text(client, m)
        flag = "OK " if ok else "FAIL"
        print(f"  [{flag}] {m:45s}  {msg}")
        if ok:
            text_ok.append(m)

    print()
    print("=== 视觉模型 ===")
    vision_ok: list[str] = []
    for m in VISION_CANDIDATES:
        ok, msg = try_vision(client, m)
        flag = "OK " if ok else "FAIL"
        print(f"  [{flag}] {m:45s}  {msg}")
        if ok:
            vision_ok.append(m)

    print()
    print("=== 推荐写入 .env ===")
    if text_ok:
        print(f"MODEL_NAME={text_ok[0]}")
    else:
        print("MODEL_NAME=  ❌ 全失败,检查 key/endpoint/账号余额")
    if vision_ok:
        print(f"VISION_MODEL_NAME={vision_ok[0]}")
    else:
        print("VISION_MODEL_NAME=  ⚠️  无视觉模型可用,VLM 兜底将不可用")


if __name__ == "__main__":
    main()
