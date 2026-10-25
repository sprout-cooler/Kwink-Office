"""数据模型（V10 3.4 / 3.5）。

分区（用户上传时指定，不靠识别推断）：
  offline_done  本周线下工作
  online_done   线上售后
  plan          下周工作计划
识别状态：pending → processing → done / failed
统计分类（M3 汇总计算）：training / offline_service / online_service / presale / unclassified
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Report(Base):
    """周报批次：一个用户一个自然周一条（周一起算，Asia/Shanghai）。"""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 周期周一日期，格式 YYYY-MM-DD
    period_start: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    # 绑定的模板版本（导出时按此版本填充；为空则用该用户最新版本）。
    # 绑定而非「总是用最新」是刻意的：模板改版后，历史周报重新导出仍走旧模板，
    # 否则同一份周报两次导出的样式会不一致（V10 4.5「历史周报绑定旧版本可追溯」）。
    template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    screenshots: Mapped[list["Screenshot"]] = relationship(back_populates="report", cascade="all, delete-orphan")


class Screenshot(Base):
    """上传的任务截图原图与归属分区。"""

    __tablename__ = "screenshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True, nullable=False)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    partition: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    md5: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # pending / processing / done / failed
    recognize_status: Mapped[str] = mapped_column(String(16), default="pending", index=True, nullable=False)
    recognize_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    report: Mapped[Report] = relationship(back_populates="screenshots")
    tasks: Mapped[list["TaskItem"]] = relationship(back_populates="screenshot", cascade="all, delete-orphan")


class TaskItem(Base):
    """截图识别出的结构化任务记录（标题/开始/结束/状态）。"""

    __tablename__ = "task_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    screenshot_id: Mapped[int] = mapped_column(ForeignKey("screenshots.id"), index=True, nullable=False)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 归属分区（冗余截图分区，跨分区移动时随截图更新；归属与识别解耦）
    partition: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 归一化后的 ISO8601（日期归一化模块产出，M2 先存识别原值与归一化结果）
    start_at: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    end_at: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    raw_status: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    # 归属星期 1~7（M3 校对可改）；0=未归组
    weekday: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 统计分类（M3「分区优先+关键词兜底」计算）
    stat_category: Mapped[str] = mapped_column(String(20), default="unclassified", nullable=False)
    extra: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    screenshot: Mapped[Screenshot] = relationship(back_populates="tasks")


class Setting(Base):
    """应用配置：key-value 持久化（通用 AI + 模块独立覆盖 + 未来扩展）。

    key 命名约定：
      ai.default.{base_url,model,api_key}     — 通用 AI 配置（所有模块默认）
      ai.{module_id}.{base_url,model,api_key} — 模块独立覆盖（如 weekly_report 用不同模型）
      app.{key}                               — 应用级配置
      manual.{report_id}.{issues|demands}     — 周报手工补充文本
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class TemplateVersion(Base):
    """周报模板版本（V10 4.5：模板文件入库带版本号，历史周报绑定旧版本可追溯）。

    设计要点：
    - 模板文件落 data/templates/<md5>.xlsx，库里只存路径与元信息，避免 DB 膨胀；
    - md5 唯一：同一模板重复上传只登记版本记录，不重复存文件；
    - owner_uid 遵循全局规则：数据归属键只来自网关注入身份（避坑指南 §3.1）；
    - 一个周报批次绑定一个模板版本（Report.template_id），导出时按绑定版本填充，
      保证「历史周报用当时的模板」而不是「用最新模板」—— 模板改版不影响已导出内容。
    """

    __tablename__ = "template_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    md5: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 版本号：同一 owner 下递增，用于展示「v1 / v2」
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 结构指纹：填充前用它做锚点校验的快速前置判断（不匹配直接阻断并提示重新校验）
    anchor_ok: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    note: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # 最后更新时间（回滚等操作会写入）；可空 —— 升级前的老记录没有该列
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExportArtifact(Base):
    """导出产物记录（V10 4.5：两产物成对产出、可回溯版本）。

    一次导出 = 一条记录 + 1~2 个文件：
      - xlsx   保真导出（Excel 成品）
      - png    区域截图（口径一：连续内容区；口径二：完整表体；超宽拆 _p1/_p2）
    文件落共享目录 exports/<用户名>/周报_<姓名>_<起-止>/，文件管理器可直接取用。
    """

    __tablename__ = "export_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True, nullable=False)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("template_versions.id"), nullable=True)
    # 周报_<姓名>_<起-止>，用于文件名与目录名
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    xlsx_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 截图可能多张（超宽分页），JSON 数组
    png_paths: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # content | full（T8 两口径）
    scope: Mapped[str] = mapped_column(String(16), default="content", nullable=False)
    # 截图 DPI
    dpi: Mapped[int] = mapped_column(Integer, default=192, nullable=False)
    task_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # ok | partial（xlsx 成功但截图失败）| failed
    status: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # 重命名时间（导出经历史重命名会写入）；可空 —— 升级前的老记录没有该列
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    report: Mapped[Report] = relationship("Report")


# ================================================================ 图片处理模块


class ImageAsset(Base):
    """图片处理模块的图片资产（用户上传原件 + 各能力产出的成品）。

    设计要点（与周报模块同构，保证账号隔离零改造）：
    - owner_uid 即数据归属键（应用账号 data_key），全表按账号隔离；
    - 文件落 `${DATA_DIR}/images/<owner_uid>/<md5>.<ext>`，库里只存路径与元信息，
      避免 DB 膨胀；**数据目录必须与数据库同命（TRIM_PKGVAR）**，否则升级即丢文件；
    - kind 区分「原件上传」与「加工产物」，source_id 指向来源图，便于溯源与链式处理；
    - meta 承载各能力的专属参数与结果（OCR 文本/坐标、压缩前后体积等），
      用 JSON 列一次解决，避免为每个能力加一张表；
    - source_id **刻意不建外键**：加工产物与原件是松耦合引用（原件被清理后产物仍应可用），
      建外键会造成「删原件被产物卡死」，与 v1.0.25 踩过的外键坑同类，故只留普通列。
    """

    __tablename__ = "image_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # original（用户上传原件）| convert | stitch | compress | transform
    kind: Mapped[str] = mapped_column(String(16), default="original", index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    md5: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    width: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 来源图 id（原件上传时为 0）
    source_id: Mapped[int] = mapped_column(Integer, default=0, index=True, nullable=False)
    # 能力专属参数与结果（OCR 文本/坐标、压缩前后体积等）
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    @property
    def file_missing(self) -> bool:
        """记录在但文件已丢失（历史遗留/被外部清理），前端据此显示失效占位。"""
        try:
            return not self.stored_path or not Path(self.stored_path).is_file()
        except OSError:
            return True


# ================================================================ 经营大屏模块


class BizCustomer(Base):
    """客户主数据（经营大屏）。

    设计要点：
    - owner_uid 即数据归属键（应用账号 data_key），全表按账号隔离；
    - 客户是全模块的**关联中枢**：出差、财务、工时都挂在客户下，
      这样「这个客户花了多少人力、出差几次、花了多少钱」才能交叉聚合；
    - name 不加唯一约束：同名客户可能是不同主体（如「XX科技」分公司与总公司），
      强约束反而制造录入障碍；重复由应用层给出提示而非阻断；
    - tags 用 JSON 数组存字符串标签（行业/等级/区域），避免为标签再开一张表。
    """

    __tablename__ = "biz_customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    # 联系人 / 联系方式 / 备注
    contact: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    address: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # 行业 / 等级 / 区域（自由文本，不做字典表 —— 字典表会显著增加录入摩擦）
    industry: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    level: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    region: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # active（合作中）| dormant（暂停）| archived（归档）
    status: Mapped[str] = mapped_column(String(16), default="active", index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class BizTrip(Base):
    """出差记录（一次出差 = 一条，含起止与关联客户）。

    - owner_uid 账号隔离；
    - customer_id 指向客户：**建真外键**（客户被删时出差记录必须一并解绑，
      否则会留下指向空气的关联）。删除客户时须先解绑所有引用并 commit，
      理由同 v1.0.25 的 ForeignKeyViolation 教训；
    - 起点/终点各存名称与经纬度（lng/lat），地名存文本便于人工录入，
      经纬度可由地图选点或地理编码回填；
    - mileage_km 里程（公里），cost_amount 该次出差的直接花费（元）。
    """

    __tablename__ = "biz_trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("biz_customers.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    # 出发地 / 目的地（名称 + 经纬度）
    origin_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    origin_lng: Mapped[float | None] = mapped_column(nullable=True)
    origin_lat: Mapped[float | None] = mapped_column(nullable=True)
    dest_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    dest_lng: Mapped[float | None] = mapped_column(nullable=True)
    dest_lat: Mapped[float | None] = mapped_column(nullable=True)
    # 计划起止日期（YYYY-MM-DD）
    start_date: Mapped[str] = mapped_column(String(10), default="", index=True, nullable=False)
    end_date: Mapped[str] = mapped_column(String(10), default="", index=True, nullable=False)
    # 交通方式（飞机/高铁/自驾/其他）
    transport: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    mileage_km: Mapped[float] = mapped_column(default=0.0, nullable=False)
    cost_amount: Mapped[float] = mapped_column(default=0.0, nullable=False)
    # planned（计划中）| ongoing（进行中）| done（已完成）| cancelled（已取消）
    status: Mapped[str] = mapped_column(String(16), default="planned", index=True, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class BizTripStop(Base):
    """出差途经点（一条出差可有多站，支撑「出差路径」连线）。

    - trip_id 指向出差：**建真外键**，删出差时随之删除（级联在业务层手动做，
      见 service.delete_trip —— 先删途经点并 commit，再删出差主记录，
      否则 ORM 同一 flush 内语句顺序由依赖图决定，会先删主表导致 FK 违规）；
    - seq 是站点顺序（1 起），路径连线按 seq 升序；
    - 不存 owner_uid：经由 trip_id 即可定位归属，冗余存储易与主表不一致。
    """

    __tablename__ = "biz_trip_stops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("biz_trips.id"), index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    lng: Mapped[float | None] = mapped_column(nullable=True)
    lat: Mapped[float | None] = mapped_column(nullable=True)
    arrive_date: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)


class BizExpense(Base):
    """财务流水（经营大屏）。

    ⚠️ 本表含**涉敏数据**（金额、客户名可能涉及商业机密），因此：
    - 默认仅创建者本人可见，所有查询强制 owner_uid 过滤；
    - 对外分享必须走 BizShare（显式勾选记录 + 有效期 + 可撤销），
      **绝不提供「按 owner 查询全部」之类的开放接口**；
    - amount 存正数，方向由 kind 决定（income 收入 / expense 支出），
      避免负数与符号混淆导致统计反号；
    - 金额用 Numeric(14,2) 存定点数，**不用 Float** —— 浮点累加会有
      0.1+0.2 类误差，财务统计不可接受。SQLite 与 PostgreSQL 均支持 Numeric。
    """

    __tablename__ = "biz_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("biz_customers.id"), nullable=True, index=True
    )
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("biz_trips.id"), nullable=True, index=True)
    # income（收入）| expense（支出）
    kind: Mapped[str] = mapped_column(String(16), default="expense", index=True, nullable=False)
    # 类别（差旅/餐饮/办公/工资/采购/其他…）自由文本
    category: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    # 发生日期 YYYY-MM-DD
    occurred_on: Mapped[str] = mapped_column(String(10), default="", index=True, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class BizTimeEntry(Base):
    """独立工时台账（经营大屏的工作量来源之一）。

    为什么独立成表而**不改 task_items**：
    - task_items 的语义是「某用户某周某个批次的截图识别产物」，主键归属周报批次，
      往里混入手填工时会破坏周报自身的统计口径与导出模板锚点；
    - 工时台账是**独立维度**：可记在客户/出差/项目下，与周报并行存在。

    - hours 存小时数（定点数，允许 0.5 这类半天粒度）；
    - task_date 是工作发生日 YYYY-MM-DD（不按周聚合，按日/按月聚合）；
    - customer_id / trip_id 均可空：不是每段工时都归属客户或出差。
    """

    __tablename__ = "biz_time_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("biz_customers.id"), nullable=True, index=True
    )
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("biz_trips.id"), nullable=True, index=True)
    # 事项描述（这段工时做了什么）
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"), nullable=False)
    task_date: Mapped[str] = mapped_column(String(10), default="", index=True, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class BizShare(Base):
    """经营大屏的选择性分享令牌（财务涉敏数据的受控外发）。

    威胁模型与设计：
    - 分享是**显式勾选 + 有时效 + 可撤销**三件套，缺一不可：
      * scope 存被勾选的记录 id 列表（JSON 数组），不是「全部财务」；
      * expires_at 到期即失效，读取时逐条比对当前时间；
      * revoked 置 1 后立即失效（不等到期）；
    - token 用 secrets.token_urlsafe 生成，**只存哈希不存明文**：
      即使数据库泄露也无法反推出可用的分享链接；
    - 明文 token 只在创建时返回一次给创建者，由其自行转发给接收人；
    - scope_ids 为空 = 不分享任何记录（创建即无效，等同不发），
      防止误操作把空范围当成「全部可见」；
    - 分享出去的视图**不含 owner_uid**，且不暴露其他未勾选的记录。
    """

    __tablename__ = "biz_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    # token 的 sha256 哈希（十六进制），明文不落库
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # 被勾选的记录 id 列表（JSON 数组 of int）
    scope_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # 分享内容的类别：expense（财务）| workload（工作量）| trip（出差）
    scope_kind: Mapped[str] = mapped_column(String(16), default="expense", nullable=False)
    # 有效期（ISO8601 datetime），到点即失效
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 1 = 已撤销，立即失效
    revoked: Mapped[int] = mapped_column(Integer, default=0, index=True, nullable=False)
    # 访问次数（用于察觉异常分享传播）
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ================================================================ 账号与数据隔离


class User(Base):
    """应用账号（注册登录 + 数据归属）。

    设计要点：
    - **data_key 是隔离的根**：全项目所有业务表用 owner_uid 隔离，而 owner_uid
      来自 Identity.uid；登录后把 Identity.uid 换成该账号的 data_key，
      所有业务逻辑自动按账号隔离，无需逐表改造。
    - **首个账号继承 NAS 账号的历史数据**：同一个 NAS 账号下创建的第一个应用账号，
      data_key 直接取 NAS 的 uid（如 "1000"）——这样升级前已有的周报/模板/导出记录
      仍然可见，不会出现「升级后数据不见了」。此后注册的账号用独立随机 key，
      彼此完全隔离。
    - **账号不跨 NAS 用户**：nas_uid 随网关 X-Trim-Userid 注入（不可伪造），
      登录时校验会话所属 nas_uid 与当前 NAS 身份一致，防止跨账号复用会话。
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("nas_uid", "username", name="uq_users_nas_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 登录名（同一 NAS 账号下唯一）
    username: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # pbkdf2_hmac('sha256', password, salt, N).hex()
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    salt: Mapped[str] = mapped_column(String(32), nullable=False)
    # 归属的 NAS 账号 uid（网关注入，客户端不可伪造）
    nas_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 数据隔离键：写入所有业务表的 owner_uid
    data_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    is_admin: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    disabled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthSession(Base):
    """登录会话（服务端签发 token → 写入 Cookie）。

    为什么不沿用 NAS 网关会话：网关只证明「是这台 NAS 的某个已登录用户」，
    无法区分应用内的多个账号。这里在网关身份之上再加一层应用会话，
    网关的身份红线（只看 X-Trim-* 头）不受影响。
    """

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    user_agent: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class UserSetting(Base):
    """按账号隔离的应用配置（owner_uid + key）。

    为什么不改原 settings 表：settings.key 是全局唯一约束，改成 (owner, key)
    需要改约束 → 现存库无法平滑升级（迁移脚本只补列，不改约束）。
    新增本表是**纯增量**：读的时候先查用户私有值，没有再回落到全局 settings
    （保留安装向导注入的默认值作为新账号起点），写入一律写私有。
    """

    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("owner_uid", "key", name="uq_user_settings_owner_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_uid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
