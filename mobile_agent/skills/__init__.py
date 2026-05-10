"""
SkillRegistry —— 启动时扫描本目录,把 SKILL 单例收集起来。

约定:每个技能模块导出一个 `SKILL` 变量,值为该技能的实例。
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mobile_agent.skills.base import Skill


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, "Skill"] = {}

    def register(self, skill: "Skill") -> None:
        if skill.name in self._skills:
            raise ValueError(f"技能名重复:{skill.name}")
        self._skills[skill.name] = skill

    def get(self, name: str) -> "Skill | None":
        return self._skills.get(name)

    def all(self) -> list["Skill"]:
        return list(self._skills.values())

    def descriptions(self) -> list[dict]:
        """供 LLM 路由用的简介列表。"""
        out = []
        for s in self._skills.values():
            out.append(
                {
                    "name": s.name,
                    "description": s.description,
                    "args_schema": s.args_schema.model_json_schema(),
                }
            )
        return out


def autoload() -> SkillRegistry:
    """扫描 mobile_agent.skills.* 子模块,收集每个模块中的 SKILL 变量。"""
    registry = SkillRegistry()
    pkg = __name__
    for mod_info in pkgutil.iter_modules(__path__):
        name = mod_info.name
        if name in ("__init__", "base"):
            continue
        mod = importlib.import_module(f"{pkg}.{name}")
        skill = getattr(mod, "SKILL", None)
        if skill is not None:
            registry.register(skill)
    return registry
