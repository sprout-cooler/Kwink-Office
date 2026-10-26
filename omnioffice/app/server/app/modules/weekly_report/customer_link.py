"""周报 ↔ 客户联动：客户名匹配规则。

为什么单独成文件：这个模块是**纯规则**，最容易出「同名误配」「匹配到了别的账号的客户」
这类静默错误 —— 工时/费用挂错客户名下，财务影响大且无报错，必须靠单测兜住。

三条铁律（来自 v1.0.30 设计）：
1. **只在同账号内匹配** —— 绝不跨账号（客户数据是账号隔离的）；
2. **同名多条 → 不猜** —— 标记 ambiguous 交人工，绝不自动挂到任意一条；
3. **匹配不到 → 不自动建客户** —— 客户是财务主数据，脏数据代价高，
   只提示「该客户未建档」，由用户决定是否新建。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 客户匹配状态
MATCH_MATCHED = "matched"      # 唯一命中，已关联
MATCH_AMBIGUOUS = "ambiguous"   # 同名多条，需人工指定
MATCH_NONE = "none"             # 没匹配到（客户未建档）
MATCH_MANUAL = "manual"         # 人工校对指定，优先级最高

# 多客户时的分隔符（与提示词里约定的「、」一致）
# ⚠️ 必须用 re 的字符集 [^...]：str.split(sep) 当 sep 是**字符串**时，
# Python 按**整串**匹配分割（实测 '甲、乙'.split('、,;') 不切），
# 会导致多个客户被当成一个名字，匹配必然失败。
_SEPARATOR_RE = re.compile(r"[、,，;；/|]")


@dataclass(frozen=True)
class CustomerMatch:
    """一次客户名匹配的结论。"""

    customer_id: int | None
    customer_name: str
    match: str          # MATCH_* 之一
    ambiguous_ids: tuple[int, ...] = ()   # 同名多条时的候选 id（供人工选择）

    @property
    def is_linked(self) -> bool:
        return self.customer_id is not None


def split_names(raw: str) -> list[str]:
    """把 AI 给的 customer 字段拆成多个客户名。

    模型可能填「甲公司、乙公司」，也可能是单个名字。
    拆分后逐个去空白、丢空项、去重（保持顺序）。
    """
    if not raw:
        return []
    parts: list[str] = []
    for seg in _SEPARATOR_RE.split(str(raw).replace("\n", "、")):
        s = seg.strip()
        if not s:
            continue
        if s not in parts:
            parts.append(s)
    return parts


def _normalize(name: str) -> str:
    """归一化客户名用于比对：去空白 + 全角空格 + 大小写。

    只做**保守**归一化：不做去括号、不去「有限公司」等后缀 ——
    那些属于语义归并，会制造「两个不同客户被合成一个」的误配风险。
    """
    return "".join(str(name or "").split()).casefold()


def match_customer(
    raw_name: str,
    candidates: list[tuple[int, str]],
) -> CustomerMatch:
    """把 AI 给的客户名匹配到客户表。

    Args:
        raw_name: AI 指认/抽取的客户名（可能含多个，用「、」分隔）。
        candidates: 同账号内的 (id, name) 列表。

    Returns:
        CustomerMatch：匹配结论。
    """
    names = split_names(raw_name)
    if not names:
        return CustomerMatch(None, "", MATCH_NONE)

    # 建归一化索引：normalized -> [(id, original_name), ...]
    index: dict[str, list[tuple[int, str]]] = {}
    for cid, cname in candidates:
        key = _normalize(cname)
        if key:
            index.setdefault(key, []).append((cid, cname))

    # 多个客户时取第一个能匹配的（多客户关联暂不支持，只取主客户）
    for name in names:
        hits = index.get(_normalize(name))
        if not hits:
            continue
        if len(hits) == 1:
            cid, cname = hits[0]
            return CustomerMatch(cid, cname, MATCH_MATCHED)
        # 同名多条 → 不猜
        return CustomerMatch(
            None,
            name,
            MATCH_AMBIGUOUS,
            ambiguous_ids=tuple(cid for cid, _ in hits),
        )

    # 一个都没匹配上：客户未建档（不自动创建）
    return CustomerMatch(None, names[0], MATCH_NONE)
