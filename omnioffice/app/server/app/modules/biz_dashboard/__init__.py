"""数据大屏模块：客户 / 出差 / 财务 / 工作量的一体化视图。

模块定位：
- **工作量**有两个来源，本模块同时支持（用户明确要求二者都要）：
  1. 周报工时 —— 只读聚合既有 task_items，不新增写入、不污染周报表；
  2. 独立工时台账 —— biz_time_entries，手工登记。
- **客户 / 出差 / 财务**是全新业务域，客户是关联中枢。

分层约定（与 image_tool 一致）：
- constants / errors / workload / geo 不碰数据库与身份，可独立调用；
- service 负责「算什么、记给谁」；
- router 是**唯一**把 BizDashboardError 翻译成 HTTP 的地方。
"""
from __future__ import annotations

from .errors import BizDashboardError

__all__ = ["BizDashboardError"]
