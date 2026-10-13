"""行号偏移映射（V10 3.6.3 关键要求）。

插行会让后续所有区块的行号漂移 —— 「插入新行时必须同步调整后续所有区块的行号，
避免工作汇总、重点问题跟进等区块错位」。

为什么不用「边插边改」：
openpyxl 的 insert_rows 不会更新合并单元格、也不移动样式，逐段手工修补极易漏。
本模块采用**先算偏移、再一次性应用**的策略：
1. 填充前先统计每个星期块需要插入几行；
2. 用 RowShifter 一次性算出「基准行 → 实际行」的映射；
3. 由调用方按实际行重建合并区间与写入。

这样插行顺序不影响结果，也不会出现「插了 A 块忘了 B 块」的错位。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RowShifter:
    """基准行 → 实际行的偏移映射。

    extra_before: {基准行: 额外插入行数}，该基准行之前累计插入的行数即为偏移。
    """

    extra_before: dict[int, int] = field(default_factory=dict)

    def add_insert(self, before_row: int, rows: int) -> None:
        """声明：在基准行 before_row 之前插入 rows 行。"""
        if rows <= 0:
            return
        self.extra_before[before_row] = self.extra_before.get(before_row, 0) + rows

    def offset_for(self, base_row: int) -> int:
        """返回基准行 base_row 累计的偏移量。

        语义：``add_insert(r, n)`` 表示「在基准行 r **所在块内部**扩展了 n 行」，
        即该块的首行仍留在 r，块的下边界下移 n 行。因此**基准行 r 自身不被推移**，
        只有严格大于 r 的行才受影响 —— 这正是 openpyxl 在 r 处 insert_rows 的实际效果
        （r 及之后的内容整体下移，r 位置被新行占据但仍属于本块）。

        所以这里必须用 ``r < base_row``，不是 ``r <= base_row``。
        """
        return sum(n for r, n in self.extra_before.items() if r < base_row)

    def actual(self, base_row: int) -> int:
        """基准行 → 实际行号。"""
        return base_row + self.offset_for(base_row)

    def actual_ref(self, ref: str) -> str:
        """把 'D17' 这类引用按偏移换算为实际单元格，如 'D21'。"""
        col = "".join(ch for ch in ref if ch.isalpha())
        row = int("".join(ch for ch in ref if ch.isdigit()))
        return f"{col}{self.actual(row)}"

    def actual_row_range(self, start: int, end: int) -> tuple[int, int]:
        """基准行区间 → 实际行区间。

        注意：这里只按**行号偏移**换算，适用于「独立区块」（汇总/问题/需求/计划）。
        星期块不能用本方法 —— 块内扩展时块高度会变，须用 block_actual()，
        否则会出现「块起始行 + 偏移」与「块结束行 + 偏移」算出重叠区间。
        """
        return self.actual(start), self.actual(end)

    def block_actual(self, start: int, end: int) -> tuple[int, int]:
        """星期块基准区间 → 实际区间（块内扩展时高度同步增长）。

        块起始行不偏移（插入发生在块内部），块结束行额外延伸本块插入的行数。
        """
        s = self.actual(start)
        inserted_here = self.extra_before.get(start, 0)
        height = (end - start) + 1 + inserted_here
        return s, s + height - 1

    def total_inserted(self) -> int:
        return sum(self.extra_before.values())

    def validate_monotonic(self, anchors) -> None:
        """填充完成后校验行号单调性与区块不重叠（V10：填充后做一次行号校验）。

        防止「某块插行后反超后续区块」这类静默错位 —— 线上只表现为导出的表错位，
        不报任何错，只能靠这个断言兜住。
        """
        # 逐块计算实际区间，检查 ① 与前一块不重叠 ② 自身不被插到撑破
        prev_end = 0
        for b in anchors.weekdays:
            start = self.actual(b.start_row)
            # 块的实际高度 = 原始高度 + 本块插入的行数
            inserted_here = self.extra_before.get(b.start_row, 0)
            height = (b.end_row - b.start_row) + 1 + inserted_here
            end = start + height - 1
            if start <= prev_end:
                raise AssertionError(
                    f"行号校验失败：星期 {b.weekday} 块实际起始行 {start} "
                    f"与前一区块（结束行 {prev_end}）重叠"
                )
            prev_end = end

        # 后续区块必须严格排在最后一个星期块之后
        regions = [
            ("工作汇总", *anchors.summary_row_range),
            ("重点问题", *anchors.issue_row_range),
            ("工作需求", *anchors.demand_row_range),
            ("下周计划", *anchors.plan_row_range),
        ]
        for name, s, e in regions:
            a_s, a_e = self.actual_row_range(s, e)
            if a_s <= prev_end:
                raise AssertionError(
                    f"行号校验失败：{name}区块实际起始行 {a_s} "
                    f"未排在最后一个星期块（结束行 {prev_end}）之后"
                )
            if a_e < a_s:
                raise AssertionError(f"行号校验失败：{name}区块首尾倒置 {a_s} > {a_e}")
