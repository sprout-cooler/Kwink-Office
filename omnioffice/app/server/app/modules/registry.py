"""模块注册表（V10 8.8）：外壳只渲染注册表数据，新增模块零包配置改动。

新增模块标准步骤：在 server/modules 与 web/src/modules 下新增目录 → 在此登记。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModuleTab:
    id: str
    name: str


@dataclass(frozen=True)
class ModuleMeta:
    id: str
    display_name: str
    icon: str
    route: str
    tabs: tuple[ModuleTab, ...] = field(default_factory=tuple)
    enabled: bool = True


# C 层 Tab 定义依据 V10 3.10
MODULES: tuple[ModuleMeta, ...] = (
    ModuleMeta(
        id="weekly_report",
        display_name="周报",
        icon="weekly-report",
        route="/weekly-report",
        tabs=(
            ModuleTab("upload", "任务上传"),
            ModuleTab("review", "识别校对"),
            ModuleTab("summary", "工作汇总"),
            ModuleTab("manual", "手工补充"),
            ModuleTab("export", "预览与导出"),
        ),
    ),
)


def list_enabled() -> list[dict]:
    return [
        {
            "id": m.id,
            "displayName": m.display_name,
            "icon": m.icon,
            "route": m.route,
            "tabs": [{"id": t.id, "name": t.name} for t in m.tabs],
        }
        for m in MODULES
        if m.enabled
    ]
