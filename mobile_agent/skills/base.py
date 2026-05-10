"""
技能基类与运行时上下文。

PRD §7.1:
  - Skill 持名字 / 描述 / args_schema / run()
  - RunContext 持 device、memory、logger、cancel_token
  - SkillResult { ok, summary, artifacts }
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from mobile_agent.utils.cancel import CancelToken

if TYPE_CHECKING:
    from mobile_agent.device.device import Device


@dataclass
class SkillResult:
    ok: bool
    summary: str
    artifacts: list[Path] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class RunContext:
    device: "Device"
    task_id: str
    task_dir: Path
    cancel_token: CancelToken
    logger: logging.Logger
    memory: object | None = None  # M5 注入


class Skill(Protocol):
    name: str
    description: str
    args_schema: type[BaseModel]

    def run(self, args: BaseModel, ctx: RunContext) -> SkillResult: ...
