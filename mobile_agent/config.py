"""读 .env / 环境变量,集中暴露配置。

为了避免密钥误推到公开仓库,密钥文件按以下优先级查找:
  1. 环境变量 MOBILE_AGENT_ENV_FILE 指向的绝对路径
  2. ~/.config/mobile-agent/.env  (推荐位置, 在项目目录之外)
  3. 项目根目录下的 .env          (兼容旧用法; 已被 .gitignore 忽略)
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _find_env_file() -> Path | None:
    explicit = os.getenv("MOBILE_AGENT_ENV_FILE")
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            return p
    user_cfg = Path.home() / ".config" / "mobile-agent" / ".env"
    if user_cfg.is_file():
        return user_cfg
    project_env = ROOT / ".env"
    if project_env.is_file():
        return project_env
    return None


_env_file = _find_env_file()
if _env_file is not None:
    load_dotenv(_env_file)


class Config:
    # LLM
    MOONSHOT_API_KEY: str = os.getenv("MOONSHOT_API_KEY", "")
    MOONSHOT_BASE_URL: str = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "kimi-latest")
    VISION_MODEL_NAME: str = os.getenv("VISION_MODEL_NAME", "moonshot-v1-32k-vision-preview")

    # 设备
    ANDROID_SERIAL: str = os.getenv("ANDROID_SERIAL", "")

    # 路径
    ROOT: Path = ROOT
    RUNS_DIR: Path = ROOT / "runs"
    DATA_DIR: Path = ROOT / "data"
    DB_PATH: Path = ROOT / "data" / "memory.db"

    # 日志
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def ensure_dirs(cls) -> None:
        cls.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def assert_llm_ready(cls) -> None:
        if not cls.MOONSHOT_API_KEY:
            raise RuntimeError(
                "MOONSHOT_API_KEY 未设置。请把密钥放到 ~/.config/mobile-agent/.env "
                "或通过 MOBILE_AGENT_ENV_FILE 环境变量指向密钥文件。"
                "格式参考项目根目录的 .env.example。"
            )


cfg = Config()
cfg.ensure_dirs()
