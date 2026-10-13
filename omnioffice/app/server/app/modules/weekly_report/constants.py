"""周报模块常量（V10 3.4.1）。"""
from __future__ import annotations

# 上传分区（用户指定，不靠识别推断）
PARTITION_OFFLINE_DONE = "offline_done"
PARTITION_ONLINE_DONE = "online_done"
PARTITION_PLAN = "plan"

PARTITIONS: tuple[tuple[str, str], ...] = (
    (PARTITION_OFFLINE_DONE, "本周线下工作"),
    (PARTITION_ONLINE_DONE, "线上售后"),
    (PARTITION_PLAN, "下周工作计划"),
)
PARTITION_IDS = {p for p, _ in PARTITIONS}
PARTITION_LABELS = dict(PARTITIONS)

# ---------------------------------------------------------------- 时间必填口径
#
# 「时间」在这份周报里的唯一作用是**决定任务落到星期几那一栏**（xlsx 的 7 个星期块）。
# 因此是否必填，取决于该分区的产出是否需要按天拆分：
#
#   - 本周线下工作（offline_done）：按天罗列具体做了什么（培训/回访/演示各有日期），
#     必须有时间才能落进对应星期块 → 必填。
#   - 线上售后（online_done）：来源多是会话量汇总截图（如「一周小结 10.5-10.9
#     处理了 413 次工作会话」），本身就是**按周汇总、只论总量**，截图上根本
#     没有逐条时刻。强行要求填时间等于逼用户编一个 → 非必填。
#   - 下周工作计划（plan）：写的是「打算做什么」，尚未发生，本无发生时间 → 非必填。
#
# 非必填 ≠ 丢数据：这类任务照样计入工作汇总数量，只是不进星期块明细。
TIME_REQUIRED_PARTITIONS = frozenset({PARTITION_OFFLINE_DONE})


def time_required(partition: str) -> bool:
    """该分区是否必须有时间才能导出。

    采用**白名单从严**语义：只有显式列在 TIME_REQUIRED_PARTITIONS 的分区才
    免时间要求。这样将来新增分区时默认仍要求填时间 —— 漏配时是「拦住用户
    多问一句」，而不是「静默放过本该校验的数据」。真要放宽时往白名单里加即可。
    """
    if partition in PARTITION_IDS:
        return partition in TIME_REQUIRED_PARTITIONS
    return True  # 未知分区从严

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_SUFFIX = {".jpg", ".jpeg", ".png", ".webp"}
