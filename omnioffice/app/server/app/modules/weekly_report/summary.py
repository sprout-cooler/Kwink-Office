"""工作汇总计算（V10 3.6 / 3.7）。

四项统计口径：**分区优先 + 关键词兜底**
- 「线上售后」按分区直接计数（用户上传时已定归属，不看标题）；
- 「培训 / 线下售后 / 售前」按标题关键词判定，多命中时按 **培训 > 售后 > 售前** 取优先级最高的；
- 未命中任何关键词 → 进入「未分类清单」，由用户手工归类；
- 用户手工覆盖后写 manual_category 并锁定，之后自动统计不再刷新该单元格。

设计要点：
1. 纯函数 + 无 IO，便于单测覆盖全部边界；
2. 关键词表为模块级常量，便于后续做成可配置（T12）；
3. 计数基于「当前批次的任务」，跨分区移动后重算即刻生效。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# ---- 统计分类（对应 TaskItem.stat_category）----------------------------------
CAT_OFFLINE = "offline"                    # 线下工作合计（培训+线下售后+售前）
CAT_TRAINING = "training"                  # 培训
CAT_OFFLINE_SERVICE = "offline_service"    # 线下售后
CAT_PRESALE = "presale"                    # 售前
CAT_ONLINE_SERVICE = "online_service"      # 线上售后（分区直计）
CAT_PLAN = "plan"                          # 下周计划（分区直计）
CAT_UNCLASSIFIED = "unclassified"          # 未分类

# 工作汇总页展示的四项 + 两项附加
SUMMARY_ITEMS: tuple[tuple[str, str], ...] = (
    (CAT_TRAINING, "培训"),
    (CAT_OFFLINE_SERVICE, "线下售后"),
    (CAT_PRESALE, "售前"),
    (CAT_ONLINE_SERVICE, "线上售后"),
)

# ---- 关键词表（V10 3.7；子串匹配，命中即算）--------------------------------
KEYWORDS: dict[str, tuple[str, ...]] = {
    CAT_TRAINING: ("培训", "实训", "授课", "教学", "分享会"),
    CAT_OFFLINE_SERVICE: ("售后", "回访", "上门", "现场支持", "驻场"),
    CAT_PRESALE: ("售前", "演示", "试用", "拜访", "商机"),
}

# 多命中时的优先级（数字越小越优先）
_PRIORITY: dict[str, int] = {
    CAT_TRAINING: 0,
    CAT_OFFLINE_SERVICE: 1,
    CAT_PRESALE: 2,
}

# 分区 → 该分区天然归属的分类（分区优先：命中即定，不再看标题关键词）
_PARTITION_CATEGORY: dict[str, str] = {
    "online_done": CAT_ONLINE_SERVICE,
    "plan": CAT_PLAN,
}


@dataclass
class TaskView:
    """汇总计算所需的最小任务视图（与 ORM 解耦，便于单测）。"""

    id: int
    partition: str
    title: str = ""
    manual_category: str | None = None  # 手工覆盖（锁定，自动统计不再刷新）


@dataclass
class SummaryResult:
    counts: dict[str, int] = field(default_factory=dict)
    unclassified: list[int] = field(default_factory=list)  # 未分类任务 id
    total: int = 0


def classify_task(task: TaskView) -> str:
    """判定单条任务的统计分类。

    顺序（不可调换）：
      1. 手工覆盖优先（锁定态，任何自动规则都不改写）；
      2. 分区优先：线上售后 / 下周计划 由上传分区直接确定；
      3. 关键词兜底：线下工作分区按标题关键词命中项，多命中取优先级最高；
      4. 兜底未命中 → unclassified（交人工归类，绝不硬塞）。
    """
    # 1. 手工覆盖
    if task.manual_category:
        return task.manual_category
    # 2. 分区优先
    cat = _PARTITION_CATEGORY.get(task.partition)
    if cat is not None:
        return cat
    # 3. 关键词兜底（仅线下工作分区需要判定）
    if task.partition == "offline_done":
        title = task.title or ""
        hits = [c for c, words in KEYWORDS.items() if any(w in title for w in words)]
        if hits:
            return min(hits, key=lambda c: _PRIORITY[c])
    return CAT_UNCLASSIFIED


def compute_summary(tasks: Iterable[TaskView]) -> SummaryResult:
    """计算工作汇总四项统计 + 未分类清单。

    返回的 counts 含四个展示项与 offline/plan/unclassified 附加项，便于前端直接渲染。
    """
    tasks = list(tasks)
    counts: dict[str, int] = {cat: 0 for cat, _ in SUMMARY_ITEMS}
    counts.update({CAT_OFFLINE: 0, CAT_PLAN: 0, CAT_UNCLASSIFIED: 0})
    unclassified: list[int] = []

    for t in tasks:
        cat = classify_task(t)
        counts[cat] = counts.get(cat, 0) + 1
        if cat == CAT_UNCLASSIFIED:
            unclassified.append(t.id)
        if cat in (CAT_TRAINING, CAT_OFFLINE_SERVICE, CAT_PRESALE):
            counts[CAT_OFFLINE] += 1

    # 未分类按 id 排序，保证前端列表稳定（便于用户逐条归类）
    unclassified.sort()
    return SummaryResult(counts=counts, unclassified=unclassified, total=len(tasks))
