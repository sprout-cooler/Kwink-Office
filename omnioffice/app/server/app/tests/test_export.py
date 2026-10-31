"""模板版本管理与导出编排测试。

覆盖：
- 模板上传（结构校验通过才入库 / 结构不符 400 / 重复 md5 去重 / 非 xlsx 拒绝）；
- 版本绑定（绑定后按绑定版本导出；删除时自动解绑，v1.0.23 契约变更）；
- 模板文件与记录的一致性（落盘持久 / 文件丢失后重传可修复 / 删除同步清文件）；
- 导出编排（卡点阻断 / 产物命名 / xlsx 落盘 / 渲染失败降级 partial）；
- 打印区域计算（T8 两口径）与渲染目录清理（不留 print_area 污染产物）。

渲染链需要 LibreOffice，本机通常没有 —— 相关用例在缺 soffice 时 skip，
其余逻辑（产物登记、路径、清理）仍完整覆盖。
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import shutil
import unittest
from pathlib import Path

from fastapi import HTTPException, UploadFile
from openpyxl import Workbook, load_workbook

from app.core.identity import Identity
from app.db.models import ExportArtifact, Report, TaskItem, TemplateVersion
from app.modules.weekly_report import export_service as ES
from app.modules.weekly_report.export_service import (
    _compute_print_area,
    _safe_name,
    report_display_name,
)

TEMPLATE = Path(__file__).parent / "fixtures" / "template_weekly.xlsx"


def ident(uid: str = "1000", name: str = "devuser") -> Identity:
    return Identity(uid=uid, username=name, is_admin=False)


def run_async(coro):
    """在独立事件循环里跑协程。

    不能直接用 asyncio.get_event_loop()：Python 3.10+ 在无运行循环时
    会 DeprecationWarning / 3.12+ 直接抛错，单测进程里并不可靠。
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ExportTestBase(unittest.TestCase):
    def setUp(self):
        from app.db.session import SessionLocal, init_db

        init_db()
        self.db = SessionLocal()
        from app.db.models import Screenshot

        for M in (ExportArtifact, TaskItem, Screenshot, Report, TemplateVersion):
            self.db.query(M).delete()
        self.db.commit()
        self.tmp = Path(__file__).parent.parent.parent.parent / ".test-export"
        self.tmp.mkdir(parents=True, exist_ok=True)
        self._orig_data_dir = ES.settings.data_dir
        ES.settings.__dict__["data_dir"] = str(self.tmp)
        self.me = ident()

    def tearDown(self):
        ES.settings.__dict__["data_dir"] = self._orig_data_dir
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.db.close()

    def make_report(self) -> Report:
        r = Report(owner_uid=self.me.uid, period_start="2026-10-12", status="draft")
        self.db.add(r)
        self.db.commit()
        self.db.refresh(r)
        return r

    def add_task(
        self,
        report: Report,
        title: str,
        weekday: int,
        conf: float = 1.0,
        reviewed: bool = True,
        partition: str = "offline_done",
        no_time: bool = False,
        warnings: list[str] | None = None,
    ):
        """走真实入库路径：手工任务挂在 __manual__ 占位截图下。

        不能直接 screenshot_id=None —— 该列是 NOT NULL（见 review_service.create_task
        用占位截图的原因）。这里复用同一机制，保证测试与生产一致。

        no_time=True 模拟「截图上本就没有时刻」的条目：weekday=0 且 start_at 为空。
        """
        from app.db.models import Screenshot

        ph = self.db.query(Screenshot).filter_by(filename="__manual__").one_or_none()
        if ph is None:
            ph = Screenshot(
                report_id=report.id,
                owner_uid=self.me.uid,
                partition=partition,
                filename="__manual__",
                stored_path="",
                md5="__manual__",
                size=0,
                content_type="text/plain",
                recognize_status="done",
            )
            self.db.add(ph)
            self.db.commit()
            self.db.refresh(ph)
        t = TaskItem(
            screenshot_id=ph.id,
            owner_uid=self.me.uid,
            partition=partition,
            title=title,
            start_at="" if no_time else "2026-10-13T10:00",
            end_at="" if no_time else "2026-10-13T11:00",
            weekday=0 if no_time else weekday,
            confidence=conf,
            stat_category="unclassified",
            extra={"reviewed": reviewed, "warnings": warnings or []},
        )
        self.db.add(t)
        self.db.commit()
        return t


class TestNamingAndSafety(unittest.TestCase):
    def test_safe_name_strips_path_separators(self):
        """文件名安全化：路径分隔符与 Windows 非法字符必须去掉。"""
        out = _safe_name("../../etc/passwd")
        self.assertNotIn("/", out)
        self.assertNotIn("\\", out)
        self.assertNotIn("..", out.strip(". "))

    def test_safe_name_fallback_when_empty(self):
        self.assertEqual(_safe_name("   "), "周报")
        self.assertEqual(_safe_name("///"), "周报")

    def test_report_display_name_range(self):
        n = report_display_name("张三", "2026-10-12")
        self.assertIn("张三", n)
        self.assertIn("2026-10-12", n)
        self.assertIn("2026-10-18", n, "结束日应为周一 + 6 天")


class TestTemplateUpload(ExportTestBase):
    def _fake_upload(self, path: Path):
        class F:
            def __init__(self, p):
                self.filename = p.name

            async def read(self):
                return path.read_bytes()

        return F(path)

    @unittest.skipUnless(TEMPLATE.is_file(), "缺少真实模板基准")
    def test_upload_valid_template(self):
        import asyncio

        r = asyncio.run(ES.upload_template(self.db, self.me, self._fake_upload(TEMPLATE)))
        self.assertFalse(r["duplicated"])
        self.assertEqual(r["template"]["version"], 1)
        self.assertTrue(Path(self.db.query(TemplateVersion).one().stored_path).is_file())

    @unittest.skipUnless(TEMPLATE.is_file(), "缺少真实模板基准")
    def test_upload_duplicate_md5_reused(self):
        import asyncio

        r1 = asyncio.run(ES.upload_template(self.db, self.me, self._fake_upload(TEMPLATE)))
        r2 = asyncio.run(ES.upload_template(self.db, self.me, self._fake_upload(TEMPLATE)))
        self.assertFalse(r1["duplicated"])
        self.assertTrue(r2["duplicated"], "同 md5 应复用已有版本")
        self.assertEqual(self.db.query(TemplateVersion).count(), 1)

    def test_upload_rejects_non_xlsx(self):
        import asyncio

        p = self.tmp / "a.xls"
        p.write_bytes(b"x")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(ES.upload_template(self.db, self.me, self._fake_upload(p)))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_upload_rejects_broken_anchor(self):
        """结构不符必须 400 阻断 —— 不能留一个填充不了的模板。"""
        import asyncio

        wb = Workbook()
        wb.active["A1"] = "随便写的表"
        bad = self.tmp / "bad.xlsx"
        wb.save(bad)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(ES.upload_template(self.db, self.me, self._fake_upload(bad)))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("ANCHOR_MISMATCH", str(ctx.exception.detail))
        self.assertEqual(self.db.query(TemplateVersion).count(), 0, "校验失败不得入库")

    def test_validation_failure_not_swallowed(self):
        """回归：入库逻辑曾被误缩进到 try 的 finally 块里。

        后果是「校验抛异常 → finally 照常执行 → 模板仍被入库，且 anchorOk=True」，
        一个完全用不了的模板被当成可用的收进来，只有到导出那天才炸。
        本用例从行为上钉死：校验失败时既不返回也不入库。
        """
        import asyncio

        wb = Workbook()
        wb.active["A1"] = "不是周报模板"
        bad = self.tmp / "not-weekly.xlsx"
        wb.save(bad)
        with self.assertRaises(HTTPException):
            asyncio.run(ES.upload_template(self.db, self.me, self._fake_upload(bad)))
        self.assertEqual(self.db.query(TemplateVersion).count(), 0)
        # 模板目录里也不该留下文件
        tdir = self.tmp / "templates"
        if tdir.is_dir():
            self.assertEqual(list(tdir.glob("*.xlsx")), [], "校验失败不应落盘")

    def test_upload_rejects_empty_file(self):
        import asyncio

        p = self.tmp / "empty.xlsx"
        p.write_bytes(b"")
        with self.assertRaises(HTTPException):
            asyncio.run(ES.upload_template(self.db, self.me, self._fake_upload(p)))

    def test_cross_user_isolation(self):
        """越权红线：拿不到别人的模板。"""
        other = ident("9999", "other")
        row = TemplateVersion(owner_uid="9999", filename="x.xlsx", stored_path="/x", md5="a" * 32, size=1)
        self.db.add(row)
        self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            ES.get_template(self.db, self.me, row.id)
        self.assertEqual(ctx.exception.status_code, 404)


class TestTemplateBinding(ExportTestBase):
    def test_bind_and_resolve(self):
        row = TemplateVersion(owner_uid=self.me.uid, filename="t.xlsx", stored_path=str(TEMPLATE), md5="b" * 32, size=1, version=1)
        self.db.add(row)
        self.db.commit()
        rep = self.make_report()
        ES.bind_template(self.db, self.me, rep, row.id)
        self.assertEqual(rep.template_id, row.id)
        self.assertEqual(ES.resolve_template(self.db, self.me, rep).id, row.id)

    def test_resolve_falls_back_to_latest(self):
        """未绑定时用该用户最新版本。"""
        row = TemplateVersion(owner_uid=self.me.uid, filename="t.xlsx", stored_path=str(TEMPLATE), md5="c" * 32, size=1, version=3)
        self.db.add(row)
        self.db.commit()
        rep = self.make_report()
        self.assertEqual(ES.resolve_template(self.db, self.me, rep).id, row.id)

    def test_resolve_without_any_template_errors(self):
        rep = self.make_report()
        with self.assertRaises(HTTPException) as ctx:
            ES.resolve_template(self.db, self.me, rep)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("NO_TEMPLATE", str(ctx.exception.detail))

    def test_delete_unbinds_instead_of_blocking(self):
        """有批次绑定时：自动解绑后删除（v1.0.23 契约变更）。

        原契约为「抛 409 拒绝删除」，出发点是怕历史周报无法再导出。
        但这在真机上造成了死结：模板文件已被升级清空、DB 记录残留时，
        409 让用户既删不掉、也传不上去（上传被判重复直接返回），
        只能不断新增模板。实际影响可控：
        历史批次的产品已入库；无绑定时 resolve_template 会回落到该用户最新版模板，
        并不会让历史周报导出失败。

        故改为：先解绑 → 再删记录 → 再删文件，全程不留脏数据。
        """
        row = TemplateVersion(owner_uid=self.me.uid, filename="t.xlsx", stored_path=str(TEMPLATE), md5="d" * 32, size=1, version=1)
        self.db.add(row)
        self.db.commit()
        rep = self.make_report()
        ES.bind_template(self.db, self.me, rep, row.id)
        self.assertEqual(rep.template_id, row.id)

        ES.delete_template(self.db, self.me, row.id)

        # 记录已删、绑定已解
        self.assertIsNone(self.db.get(TemplateVersion, row.id))
        self.db.refresh(rep)
        self.assertIsNone(rep.template_id)
        # 越权红线不受影响：别人的模板仍删不掉
        other = TemplateVersion(owner_uid="9999", filename="x.xlsx", stored_path=str(TEMPLATE), md5="f" * 32, size=1, version=1)
        self.db.add(other)
        self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            ES.delete_template(self.db, self.me, other.id)
        self.assertEqual(ctx.exception.status_code, 404)


@unittest.skipUnless(TEMPLATE.is_file(), "缺少真实模板基准")
class TestTemplatePersistence(ExportTestBase):
    """模板「文件 ↔ 记录」一致性回归（v1.0.23 修复的事故）。

    真机事故链：DATA_DIR 曾指向安装目录 ${TRIM_APPDEST}/share（升级清空），
    而数据库在 ${TRIM_PKGVAR}（升级保留）→ 升级后必然出现
    「记录在、文件没了」→ 用户删不掉（外键/409）、重复上传被判重复而无效。
    以下用例逐条钉住修复后的行为，防止同类回归。
    """

    def _bytes(self) -> bytes:
        return TEMPLATE.read_bytes()

    def _upload(self, note: str = ""):
        """走真实上传入口（结构校验 → 落盘 → 查重 → 入库）。"""
        return run_async(
            ES.upload_template(
                self.db, self.me,
                UploadFile(filename=TEMPLATE.name, file=io.BytesIO(self._bytes())),
                note,
            )
        )

    def test_upload_persists_file_to_disk(self):
        """1) 模板文件真正落盘，且重启后仍可访问。"""
        r = self._upload()
        tpl = r["template"]
        p = Path(tpl["id"] and self.db.get(TemplateVersion, tpl["id"]).stored_path)
        self.assertTrue(p.is_file(), f"模板文件未落盘: {p}")
        self.assertEqual(p.read_bytes(), self._bytes())
        # 文件名即 md5，便于按内容精确定位（自愈策略 2）
        self.assertEqual(p.name, f"{self.db.get(TemplateVersion, tpl['id']).md5}.xlsx")

    def test_reupload_after_file_vanished_repairs_it(self):
        """3) 核心回归：文件被清空后重新上传同一模板，必须把文件补回来。"""
        first = self._upload()["template"]
        stored = Path(self.db.get(TemplateVersion, first["id"]).stored_path)
        # 模拟升级清空安装目录：文件没了，记录还在
        stored.unlink()
        self.assertFalse(stored.is_file())
        self.assertIsNotNone(self.db.get(TemplateVersion, first["id"]))

        again = self._upload()

        # 复用同一记录（不新增版本），且文件已修复
        self.assertEqual(again["template"]["id"], first["id"])
        self.assertTrue(again["duplicated"])
        self.assertTrue(stored.is_file(), "重复上传后模板文件仍未修复 —— 用户将永远无法恢复")
        self.assertEqual(stored.read_bytes(), self._bytes())
        self.assertEqual(
            self.db.query(TemplateVersion).filter(TemplateVersion.owner_uid == self.me.uid).count(), 1
        )

    def test_reupload_repairs_stale_path(self):
        """文件存在但 DB 指向旧路径（升级前安装目录）时，重传应把路径校准回来。"""
        first = self._upload()["template"]
        row = self.db.get(TemplateVersion, first["id"])
        row.stored_path = "/nonexistent/legacy/templates/old.xlsx"
        self.db.commit()

        self._upload()

        row = self.db.get(TemplateVersion, first["id"])
        self.assertTrue(Path(row.stored_path).is_file(), "stale stored_path 未被校准")
        self.assertEqual(row.size, len(self._bytes()))

    def test_delete_removes_both_record_and_file(self):
        """2) 删除模板时记录与文件同步清理，不留脏数据。"""
        r = self._upload()["template"]
        row = self.db.get(TemplateVersion, r["id"])
        stored = Path(row.stored_path)
        self.assertTrue(stored.is_file())

        ES.delete_template(self.db, self.me, r["id"])

        self.assertIsNone(self.db.get(TemplateVersion, r["id"]))
        self.assertFalse(stored.is_file(), "删记录后模板文件残留 → 孤儿文件会被 _rebuild 重新登记")

    def test_delete_succeeds_even_when_file_already_missing(self):
        """文件已丢失时也必须删得掉 —— 这正是用户被卡住的那个死结。"""
        r = self._upload()["template"]
        row = self.db.get(TemplateVersion, r["id"])
        Path(row.stored_path).unlink()

        ES.delete_template(self.db, self.me, r["id"])  # 不应抛异常

        self.assertIsNone(self.db.get(TemplateVersion, r["id"]))

    def test_version_no_collision_after_delete(self):
        """版本号取 max+1：删掉中间版本后新模板不得与现存版本撞号。

        回归点：原实现用「记录条数 + 1」算版本号，删过模板后条数变小，
        新模板会与现存记录撞号（界面出现两个 v2）。
        """
        # 造一条 version=5 的记录，再删掉它，制造版本空洞
        a = self._upload()["template"]
        row = self.db.get(TemplateVersion, a["id"])
        row.version = 5
        self.db.commit()
        ES.delete_template(self.db, self.me, a["id"])
        self.assertEqual(
            self.db.query(TemplateVersion).filter(TemplateVersion.owner_uid == self.me.uid).count(), 0
        )

        # 全新上传：max 为空 → 应得 v1，而不是「条数+1」之外的任何错值
        again = self._upload()["template"]
        self.assertEqual(again["version"], 1)

        # 再造空洞：把这条设成 v5 后删掉，然后上传一个**内容不同**的模板
        row2 = self.db.get(TemplateVersion, again["id"])
        keep = self._upload()["template"]  # 同内容复用同一条记录
        self.assertEqual(keep["id"], again["id"])
        row2.version = 5
        self.db.commit()

        # 构造内容不同但结构仍合格的模板（改一个非锚点单元格的值）
        wb = load_workbook(TEMPLATE)
        ws = wb[wb.sheetnames[0]]
        ws["A1"] = "变体模板"
        buf = io.BytesIO()
        wb.save(buf)
        data = buf.getvalue()
        self.assertNotEqual(hashlib.md5(data).hexdigest(), row2.md5)

        r2 = run_async(
            ES.upload_template(self.db, self.me, UploadFile(filename="variant.xlsx", file=io.BytesIO(data)))
        )
        # max=5 → 应得 6；若仍按「记录条数+1」则会得 2，与现存 v5 不冲突但顺序错乱
        self.assertEqual(r2["template"]["version"], 6)
        self.assertNotEqual(r2["template"]["id"], again["id"])


@unittest.skipUnless(TEMPLATE.is_file(), "缺少真实模板基准")
class TestExportFlow(ExportTestBase):
    def _install_template(self) -> TemplateVersion:
        row = TemplateVersion(
            owner_uid=self.me.uid,
            filename="本周工作总结.xlsx",
            stored_path=str(TEMPLATE),
            md5="e" * 32,
            size=TEMPLATE.stat().st_size,
            version=1,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def test_export_creates_xlsx(self):
        self._install_template()
        rep = self.make_report()
        self.add_task(rep, "任务甲", 1)
        self.add_task(rep, "任务乙", 4)
        self.add_task(rep, "任务丙", 4)
        r = ES.export_weekly_report(self.db, self.me, rep, render_png=False)
        xp = Path(r.xlsx_path)
        self.assertTrue(xp.is_file(), "xlsx 应落盘")
        self.assertTrue(xp.name.startswith("周报_devuser_2026-10-12"))
        art = self.db.get(ExportArtifact, r.artifact_id)
        self.assertIsNotNone(art)
        self.assertEqual(art.task_count, 3)

    def test_export_xlsx_content_correct(self):
        """导出的 xlsx 里应有新数据且序列号按本次周期重算。"""
        self._install_template()
        rep = self.make_report()
        self.add_task(rep, "新任务X", 1)
        ES.export_weekly_report(self.db, self.me, rep, render_png=False)
        art = self.db.query(ExportArtifact).one()
        ws = load_workbook(art.xlsx_path).active
        # 2026-10-12 的 Excel 序列号（1899-12-30 基准）
        from datetime import date as _d

        from app.modules.weekly_report.fill import excel_serial

        self.assertEqual(ws["C3"].value, excel_serial(_d(2026, 10, 12)))
        found = [ws[f"D{r}"].value for r in range(3, 20)]
        self.assertIn("新任务X", found)
        # 模板样例应已清空
        self.assertNotIn("韶关-学成口腔-一体机-售后回访（交叉检测）", [str(v) for v in found])

    def test_export_without_template_errors(self):
        rep = self.make_report()
        with self.assertRaises(HTTPException) as ctx:
            ES.export_weekly_report(self.db, self.me, rep, render_png=False)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_export_rejects_bad_scope(self):
        self._install_template()
        rep = self.make_report()
        with self.assertRaises(HTTPException):
            ES.export_weekly_report(self.db, self.me, rep, scope="weird", render_png=False)

    def test_render_failure_degrades_to_partial(self):
        """LibreOffice 不可用时不得让整个导出失败 —— xlsx 已产出，标 partial。"""
        self._install_template()
        rep = self.make_report()
        self.add_task(rep, "任务", 1)
        orig = ES._soffice_bin
        ES._soffice_bin = lambda: None  # 模拟容器缺 LibreOffice
        try:
            r = ES.export_weekly_report(self.db, self.me, rep, render_png=True)
        finally:
            ES._soffice_bin = orig
        self.assertEqual(r.status, "partial")
        self.assertTrue(Path(r.xlsx_path).is_file(), "xlsx 仍应产出")
        self.assertEqual(r.png_paths, [])

    def test_artifact_listing(self):
        self._install_template()
        rep = self.make_report()
        self.add_task(rep, "任务", 1)
        ES.export_weekly_report(self.db, self.me, rep, render_png=False)
        items = ES.list_artifacts(self.db, self.me, rep)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["xlsxExists"])


class TestPrintArea(unittest.TestCase):
    @unittest.skipUnless(TEMPLATE.is_file(), "缺少真实模板基准")
    def test_full_scope_uses_template_body(self):
        area = _compute_print_area(TEMPLATE, "full")
        self.assertEqual(area, "A1:F26")

    @unittest.skipUnless(TEMPLATE.is_file(), "缺少真实模板基准")
    def test_content_scope_is_bounding_box(self):
        """口径一：最小外接矩形。模板 D25 有内容 → 应至少到 25 行。"""
        area = _compute_print_area(TEMPLATE, "content")
        self.assertTrue(area.startswith("A1:"))
        end = int("".join(c for c in area.split(":")[1] if c.isdigit()))
        self.assertGreaterEqual(end, 25, "模板 D25~D26 有计划内容，不应被截断")

    @unittest.skipUnless(TEMPLATE.is_file(), "缺少真实模板基准")
    def test_render_leaves_no_temp_dir(self):
        """渲染结束必须清理临时目录 —— 否则残留副本会带 print_area 污染。"""
        if not shutil.which("soffice") and not shutil.which("soffice.exe"):
            self.skipTest("本机无 LibreOffice")
        out = Path(__file__).parent.parent.parent.parent / ".test-render"
        out.mkdir(parents=True, exist_ok=True)
        try:
            xp = out / "t.xlsx"
            shutil.copy2(TEMPLATE, xp)
            ES.render_region_pngs(xp, out, "t", scope="content", dpi=96)
            leftovers = [p.name for p in out.iterdir() if p.name.startswith(".render_")]
            self.assertEqual(leftovers, [], "渲染临时目录未清理")
            # 产物 xlsx 不应带 print_area
            ws = load_workbook(xp).active
            self.assertFalse(ws.print_area, "产物 xlsx 不应残留 print_area")
        finally:
            shutil.rmtree(out, ignore_errors=True)


class TestTimeRequiredByPartition(ExportTestBase):
    """时间必填按分区判定（线上售后按周汇总会话量，不应有时刻要求）。

    背景：周报的「时间」唯一作用是决定任务落进哪个星期块。线上售后来源多是
    「一周小结 / 处理了 N 次工作会话」这类汇总截图，截图上根本没有逐条时刻，
    强行必填等于逼用户编造数据。下周计划同理（尚未发生）。
    """

    def _readiness(self, report: Report) -> dict:
        from app.modules.weekly_report import review_service as RS

        return RS.export_readiness(self.db, self.me, report)

    def _install_template(self) -> TemplateVersion:
        row = TemplateVersion(
            owner_uid=self.me.uid,
            filename="本周工作总结.xlsx",
            stored_path=str(TEMPLATE),
            md5="a" * 32,
            size=TEMPLATE.stat().st_size if TEMPLATE.is_file() else 1,
            version=1,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def test_time_required_matrix(self):
        """只有「本周线下工作」要求时间。"""
        from app.modules.weekly_report.constants import time_required

        self.assertTrue(time_required("offline_done"), "线下工作按天罗列，时间必填")
        self.assertFalse(time_required("online_done"), "线上售后按周汇总会话量，时间非必填")
        self.assertFalse(time_required("plan"), "下周计划尚未发生，时间非必填")
        self.assertTrue(time_required("未知分区"), "未知分区从严按必填处理")

    def test_online_no_time_does_not_block_export(self):
        """线上售后无时间：不阻断导出，且给出非阻断提示告知去向。"""
        rep = self.make_report()
        self.add_task(rep, "本周处理413次工作会话", weekday=0,
                      partition="online_done", no_time=True)
        r = self._readiness(rep)
        self.assertTrue(r["ready"], f"线上售后无时间不应阻断导出，实际卡点：{r['reasons']}")
        codes = [n["code"] for n in r["notices"]]
        self.assertIn("TIME_OPTIONAL", codes, "应提示该条目只计入汇总数量")

    def test_online_date_parse_failed_does_not_block(self):
        """线上售后时间解析失败：属非必填分区，不应卡住导出。"""
        rep = self.make_report()
        self.add_task(rep, "会话量汇总", weekday=0, partition="online_done",
                      no_time=True, warnings=["DATE_PARSE_FAILED"])
        r = self._readiness(rep)
        self.assertTrue(r["ready"], f"线上售后解析失败不应阻断：{r['reasons']}")
        self.assertNotIn("TIME_PARSE_FAILED", [x["code"] for x in r["reasons"]])

    def test_plan_no_time_does_not_block(self):
        """下周计划无时间：同样不阻断。"""
        rep = self.make_report()
        self.add_task(rep, "下周跟进佛山客户验收", weekday=0,
                      partition="plan", no_time=True)
        r = self._readiness(rep)
        self.assertTrue(r["ready"], f"下周计划无时间不应阻断：{r['reasons']}")

    def test_offline_date_parse_failed_still_blocks(self):
        """线下工作解析失败仍必须阻断 —— 它要落进具体某天的星期块。"""
        rep = self.make_report()
        self.add_task(rep, "韶关-学成口腔-回访", weekday=0,
                      partition="offline_done", no_time=True,
                      warnings=["DATE_PARSE_FAILED"])
        r = self._readiness(rep)
        self.assertFalse(r["ready"], "线下工作时间解析失败必须阻断")
        self.assertIn("TIME_PARSE_FAILED", [x["code"] for x in r["reasons"]])

    def test_notices_never_affect_ready(self):
        """非阻断提示不得影响 ready 判定（线上+线下混合，线下有则仍阻断）。"""
        rep = self.make_report()
        self.add_task(rep, "线上会话汇总", weekday=0, partition="online_done", no_time=True)
        self.add_task(rep, "线下回访", weekday=2, partition="offline_done")
        r = self._readiness(rep)
        self.assertTrue(r["ready"])
        self.assertTrue(r["notices"], "应存在非阻断提示")
        self.assertEqual(r["reasons"], [], "无阻断项")

    def test_omitted_tasks_reported_not_silently_dropped(self):
        """无时间条目不得被静默丢弃：必须回报条数，并仍计入汇总数量。"""
        from app.modules.weekly_report import review_service as RS

        rep = self.make_report()
        self._install_template()
        self.add_task(rep, "线上会话413次", weekday=0, partition="online_done", no_time=True)
        self.add_task(rep, "线下培训", weekday=1, partition="offline_done")

        # _load_tasks_for_export 返回 (星期块明细, 下周计划标题, 未落明细条目)
        items, _plan_titles, omitted = ES._load_tasks_for_export(self.db, self.me, rep)
        self.assertEqual(len(items), 1, "只有有时间的那条进星期块明细")
        self.assertEqual([o["title"] for o in omitted], ["线上会话413次"])
        self.assertEqual(omitted[0]["partition"], "online_done")

        # 关键：汇总数量仍应算上它（线上售后按分区直计，与时间无关）
        counts = ES._summary_counts(self.db, self.me, rep)
        self.assertEqual(counts.get("online_service"), 1, "无时间条目仍应计入线上售后数量")

    def test_export_marks_omitted_in_artifact_note(self):
        """导出产物需如实告知「已计入汇总、未进明细」。"""
        rep = self.make_report()
        self._install_template()
        self.add_task(rep, "线上会话413次", weekday=0, partition="online_done", no_time=True)
        res = ES.export_weekly_report(self.db, self.me, rep, render_png=False)
        self.assertIn("未写入星期块明细", res.error)
        self.assertIn("线上会话413次", res.error)


@unittest.skipUnless(TEMPLATE.is_file(), "缺少真实模板基准")
class TestExportDiagnostics(ExportTestBase):
    """导出链路可诊断性（v1.0.16）。

    背景：真机「导出全部 500」，但服务端既没全局异常处理器、也没给可读原因，
    用户只能看到 Internal Server Error。这类故障必须在**抛出点**就转成
    带error code 与修复指引的错误，而不是裸500。
    """

    def _install_template(self) -> TemplateVersion:
        row = TemplateVersion(
            owner_uid=self.me.uid,
            filename="本周工作总结.xlsx",
            stored_path=str(TEMPLATE),
            md5="b" * 32,
            size=TEMPLATE.stat().st_size if TEMPLATE.is_file() else 1,
            version=1,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def test_unwritable_dir_gives_actionable_error(self):
        """目录不可写 → STORAGE_UNAVAILABLE 且提示具体原因，而非裸 OSError。"""
        from app.modules.weekly_report import export_service as ES

        orig = ES.settings.data_dir
        blocked = self.tmp / "blocked"
        blocked.write_text("not a dir", encoding="utf-8")  # 占位文件挡在路径上
        ES.settings.__dict__["data_dir"] = str(blocked)
        try:
            with self.assertRaises(HTTPException) as ctx:
                ES.exports_root("1000")
            self.assertEqual(ctx.exception.status_code, 500)
            self.assertEqual(ctx.exception.detail["error"], "STORAGE_UNAVAILABLE")
            self.assertIn("共享目录", ctx.exception.detail["message"])
        finally:
            ES.settings.__dict__["data_dir"] = orig

    def test_readonly_dir_detected_by_probe(self):
        """mkdir 成功但不可写（只读挂载）→ STORAGE_READONLY。"""
        from app.modules.weekly_report import export_service as ES

        ro = self.tmp / "ro"
        ro.mkdir(parents=True, exist_ok=True)
        target = ro / "exports" / "1000"
        target.mkdir(parents=True, exist_ok=True)
        # 用 patch 让写探针失败，模拟只读挂载
        from unittest import mock

        orig = ES.settings.data_dir
        ES.settings.__dict__["data_dir"] = str(ro)
        real_write = Path.write_text

        def boom(self, *a, **k):
            if self.name == ".write_probe":
                raise OSError(30, "Read-only file system")
            return real_write(self, *a, **k)

        try:
            with mock.patch.object(Path, "write_text", boom):
                with self.assertRaises(HTTPException) as ctx:
                    ES._ensure_dir(target, "导出产物")
            self.assertEqual(ctx.exception.detail["error"], "STORAGE_READONLY")
            self.assertIn("挂载权限", ctx.exception.detail["message"])
        finally:
            ES.settings.__dict__["data_dir"] = orig

    def test_missing_template_file_gone(self):
        """模板记录在库、文件被删 → TEMPLATE_FILE_GONE（410）而非裸 FileNotFoundError。"""
        tpl = self._install_template()
        Path(tpl.stored_path).unlink(missing_ok=True) if Path(tpl.stored_path) != TEMPLATE else None
        # 不动基准文件时改为指向不存在的路径
        if Path(tpl.stored_path).is_file():
            tpl.stored_path = str(self.tmp / "deleted.xlsx")
            self.db.commit()
        rep = self.make_report()
        from app.modules.weekly_report import export_service as ES

        with self.assertRaises(HTTPException) as ctx:
            ES.resolve_template(self.db, self.me, rep)
        self.assertEqual(ctx.exception.status_code, 410)
        self.assertEqual(ctx.exception.detail["error"], "TEMPLATE_FILE_GONE")
        self.assertIn("重新上传", ctx.exception.detail["message"])

    def test_corrupt_template_gives_readable_error(self):
        """模板文件损坏 → FILL_FAILED 且提示重新上传，不再是无信息的 500。"""
        tpl = self._install_template()
        bad = self.tmp / "corrupt.xlsx"
        bad.write_bytes(b"this is not a valid xlsx file at all")
        tpl.stored_path = str(bad)
        self.db.commit()
        rep = self.make_report()
        from app.modules.weekly_report import export_service as ES

        with self.assertRaises(HTTPException) as ctx:
            ES.export_weekly_report(self.db, self.me, rep, render_png=False)
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(ctx.exception.detail["error"], "FILL_FAILED")
        self.assertIn("重新上传", ctx.exception.detail["message"])

    def test_ensure_dir_returns_path_on_success(self):
        """正常路径必须照常返回，不能因加固而影响既有导出。"""
        from app.modules.weekly_report import export_service as ES

        orig = ES.settings.data_dir
        ES.settings.__dict__["data_dir"] = str(self.tmp)
        try:
            p = ES._ensure_dir(self.tmp / "ok" / "deep", "测试")
            self.assertTrue(p.is_dir())
        finally:
            ES.settings.__dict__["data_dir"] = orig


class TestGlobalErrorHandler(unittest.TestCase):
    """全局异常处理器：裸异常必须变成可定位的 500。

    注意用**真实 HTTP 请求**而非 TestClient —— TestClient 会把异常直接抛回调用方
    （raise_server_exceptions=True 默认），测不到处理器真正做了什么。
    这里起一个临时端口的真实 uvicorn，用 urllib 发请求，与真机行为一致。
    """

    @classmethod
    def setUpClass(cls):
        import socket
        import threading
        import time

        import uvicorn

        from app.main import app

        # 必须把路由**插到 SPA 兜底路由之前**。
        # main.py 末尾有 @app.get("/{full_path:path}") 兜底：任何 GET 请求匹配不到
        # 具体路由时都会返回 index.html（200 text/html）。
        # app.get / include_router 都是 append 到末尾 → 追加的路由永远排在兜底之后，
        # 请求全被吃掉，既测不到处理器也会误判成"处理器没生效"。
        # 这里直接操作 router.routes，把探针插到第一条 SPA 兜底路由之前。
        async def _boom(request):
            raise RuntimeError("模拟真机导出崩溃")

        from starlette.routing import Route

        probe = Route("/api/__test_boom__", _boom, methods=["GET"])
        spa_idx = next(
            (
                i
                for i, rt in enumerate(app.router.routes)
                if getattr(rt, "path", "") == "/{full_path:path}"
            ),
            len(app.router.routes),
        )
        app.router.routes.insert(spa_idx, probe)

        cls.app = app

        def _free_port() -> int:
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
            s.close()
            return p

        cls.port = _free_port()
        cfg = uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="error")
        cls.server = uvicorn.Server(cfg)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        # 等端口就绪
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def _get(self, path: str) -> tuple:
        import urllib.error
        import urllib.request

        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def test_handler_registered(self):
        self.assertIn(
            Exception, self.app.exception_handlers,
            "必须注册全局 Exception 处理器",
        )

    def test_unhandled_returns_structured_500(self):
        """未预期异常 → 含 requestId 的结构化 500（不是空白 Internal Server Error）。"""
        import json

        code, body = self._get("/api/__test_boom__")
        self.assertEqual(code, 500)
        d = json.loads(body)["detail"]
        self.assertEqual(d["error"], "INTERNAL_ERROR")
        self.assertIn("requestId", d, "必须给可检索编号，否则日志无法对账")
        self.assertIn("RuntimeError", d["message"])

    def test_health_diag_never_500s(self):
        """诊断接口自身不能因异常 500 —— 排障工具挂了最讽刺。"""
        import json

        code, body = self._get("/api/health/diag")
        self.assertEqual(code, 200, body)
        d = json.loads(body)
        for key in ("database", "directories", "render", "templates"):
            self.assertIn(key, d)
        for name in ("data", "templates", "exports"):
            self.assertIn("writable", d["directories"][name])
        self.assertIn("kind", d["database"])


@unittest.skipUnless(TEMPLATE.is_file(), "缺少真实模板基准")
class TestTemplateSelfHeal(ExportTestBase):
    """模板记录与文件不同步时**自动修复**，而不是让用户重新上传。

    背景（v1.0.17）：v1.0.16 只把「模板丢失」从裸 500 变成 410，但 410 是死路 ——
    用户已填完一整周周报，却因一个文件被要求重新上传。真正该做的是**自愈**：
    记录在文件没了 → 从目录找回；记录没了文件在 → 重建记录。
    """

    def setUp(self):
        super().setUp()
        from app.modules.weekly_report import export_service as ES

        self.tdir = ES.templates_root()
        for f in self.tdir.glob("*.xlsx"):
            f.unlink()
        self.backup = self.tdir / "backup_tpl.xlsx"
        shutil.copy2(TEMPLATE, self.backup)

    def tearDown(self):
        from app.modules.weekly_report import export_service as ES

        for f in ES.templates_root().glob("*.xlsx"):
            f.unlink(missing_ok=True)
        super().tearDown()

    def _template_pointing_to(self, target: Path) -> TemplateVersion:
        row = TemplateVersion(
            owner_uid=self.me.uid, filename="周报.xlsx",
            stored_path=str(target), md5="c" * 32, size=1, version=1,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def test_recovers_when_file_vanished(self):
        """记录在、文件没了 → 自动从目录找回，用户无需重新上传。"""
        from app.modules.weekly_report import export_service as ES

        gone = self.tdir / "vanished.xlsx"
        tpl = self._template_pointing_to(gone)
        rep = self.make_report()
        got = ES.resolve_template(self.db, self.me, rep)
        self.assertEqual(Path(got.stored_path).name, "backup_tpl.xlsx")
        self.assertTrue(Path(got.stored_path).is_file())
        # 路径应已修正回 DB
        self.assertEqual(tpl.stored_path, str(self.backup))

    def test_skips_broken_candidates(self):
        """目录里混入坏文件时，必须跳过它选中可用那份（不能把坏文件当恢复成功）。"""
        from app.modules.weekly_report import export_service as ES

        (self.tdir / "junk.xlsx").write_text("not a real xlsx", encoding="utf-8")
        tpl = self._template_pointing_to(self.tdir / "vanished.xlsx")
        rep = self.make_report()
        got = ES.resolve_template(self.db, self.me, rep)
        self.assertEqual(Path(got.stored_path).name, "backup_tpl.xlsx")

    def test_rebuilds_when_record_lost(self):
        """记录丢失、文件仍在 → 自动重建记录（不该提示"尚未上传模板"）。"""
        from app.modules.weekly_report import export_service as ES

        rep = self.make_report()
        self.assertEqual(self.db.query(TemplateVersion).count(), 0)
        got = ES.resolve_template(self.db, self.me, rep)
        self.assertIsNotNone(got)
        self.assertEqual(self.db.query(TemplateVersion).count(), 1)
        self.assertEqual(Path(got.stored_path).name, "backup_tpl.xlsx")

    def test_gives_up_when_nothing_usable(self):
        """目录里也确实没有可用文件 → 才报错，且提示要说明周报内容不会丢。"""
        from app.modules.weekly_report import export_service as ES

        for f in self.tdir.glob("*.xlsx"):
            f.unlink()
        (self.tdir / "junk.xlsx").write_text("broken", encoding="utf-8")
        tpl = self._template_pointing_to(self.tdir / "vanished.xlsx")
        rep = self.make_report()
        with self.assertRaises(HTTPException) as ctx:
            ES.resolve_template(self.db, self.me, rep)
        self.assertEqual(ctx.exception.status_code, 410)
        self.assertEqual(ctx.exception.detail["error"], "TEMPLATE_FILE_GONE")
        self.assertIn("周报内容不会丢", ctx.exception.detail["message"])


class TestDiagLog(unittest.TestCase):
    """真机诊断日志（v1.0.18）：本机复现不了真机问题，日志是唯一证据来源。"""

    def setUp(self):
        self.tmp = Path(__file__).parent.parent.parent.parent / ".test-diag"
        self.tmp.mkdir(parents=True, exist_ok=True)
        from app.core import diag

        self.diag = diag
        self._orig = diag._resolved_dir
        self._orig_env = os.environ.get("DIAG_LOG_DIR")
        os.environ["DIAG_LOG_DIR"] = str(self.tmp)
        diag._resolved_dir = None

    def tearDown(self):
        from app.core import diag

        if self._orig_env is None:
            os.environ.pop("DIAG_LOG_DIR", None)
        else:
            os.environ["DIAG_LOG_DIR"] = self._orig_env
        diag._resolved_dir = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_snapshot_writes_file(self):
        """快照必须真的落盘，且含关键小节。"""
        from app.db.session import init_db

        init_db()
        self.diag.snapshot("单测快照")
        log = self.diag.read_all()
        self.assertIn("单测快照", log)
        for section in ("[运行环境]", "[配置]", "[数据目录]",
                        "[数据库里的模板记录]", "[渲染链依赖]", "[挂载信息]"):
            self.assertIn(section, log, f"缺少小节 {section}")

    def test_snapshot_does_not_leak_db_password(self):
        """诊断日志会被人转发，绝不能带出数据库密码。"""
        from app.db.session import init_db

        init_db()
        from app.core import diag as d

        orig = d.settings.database_url
        object.__setattr__(
            d.settings, "database_url", "postgresql://user:secretpwd@pg:5432/db"
        )
        try:
            text_ = d.snapshot("密码泄漏检查")
        finally:
            object.__setattr__(d.settings, "database_url", orig)
        self.assertNotIn("secretpwd", text_, "诊断日志绝不能包含数据库密码")
        self.assertIn("pg:5432", text_, "应保留主机端口便于排查")

    def test_template_records_dumped(self):
        """模板记录段必须能读出 —— 这是定位 410 的核心证据。"""
        from app.db.session import SessionLocal, init_db

        init_db()
        from app.db.models import TemplateVersion

        db = SessionLocal()
        try:
            # 原来这里有一句 `db.query(TemplateVersion).delete()`，用来"清场"
            # 让 dump 输出干净。但这是**多余的**，而且会随机把整个测试套件带崩：
            #   ① 本类测试共用同一个持久化库（SessionLocal），前面的用例可能已建出
            #      reports 行，其 template_id 有外键引用 template_versions；
            #   ② DELETE FROM template_versions 撞外键 → sqlite3.IntegrityError。
            # 该失败与本用例要验证的东西完全无关（验证目标是"dump 能读出表名"，
            # 与表里有没有行无关），所以直接去掉删除动作。
            db.query(TemplateVersion).count()
        finally:
            db.close()
        out = self.diag._dump_template_records()
        self.assertIn("template_versions", out)

    def test_trace_records_failure(self):
        """导出失败时的 trace 应写入日志。"""
        from app.db.session import init_db

        init_db()
        self.diag.trace("测试失败点", "detail here")
        self.assertIn("测试失败点", self.diag.read_all())

    def test_write_failure_never_raises(self):
        """日志写不进去时不能抛异常 —— 诊断工具自己搞挂服务是最讽刺的失败。"""
        from app.core import diag as d

        self.diag.trace("正常写入", "x")
        d._resolved_dir = Path("Z:/definitely/not/exist/dir")  # 不可写
        try:
            d.trace("应静默失败", "y")
            d.snapshot("应静默失败")
            self.assertIsNone(d.diag_dir())
        finally:
            d._resolved_dir = None

    def test_no_vol_path_probe_on_windows(self):
        """非 POSIX 环境不得探测 /vol2 —— Windows 上会误建 \\vol2 目录。"""
        import os as _os

        if _os.name == "posix":
            self.skipTest("POSIX 环境本就会探测 vol2")
        self.assertEqual(self.diag._VOL_CANDIDATES, ())

    def test_screenshot_missing_detected(self):
        """截图原图缺失必须被识别 —— 真机 410 Gone 的核心证据。

        ≤1.0.18 把用户数据挂 ${TRIM_APPDEST}/share（安装 target），升级时该目录
        被清空 → DB 记录还在、原图没了 → 前端回显 410 Gone。
        """
        from app.db.models import Report, Screenshot
        from app.db.session import SessionLocal, init_db

        init_db()
        up = self.tmp / "uploads" / "1000" / "1"
        up.mkdir(parents=True, exist_ok=True)
        alive = up / "alive.png"
        alive.write_bytes(b"\x89PNG" + b"0" * 40)

        db = SessionLocal()
        try:
            db.query(Screenshot).delete()
            db.commit()
            rep = db.query(Report).first()
            if rep is None:
                rep = Report(owner_uid="1000", period_start="2026-10-13", status="draft")
                db.add(rep)
                db.commit()
                db.refresh(rep)
            db.add_all(
                [
                    Screenshot(report_id=rep.id, owner_uid="1000", partition="online_done",
                               filename="alive.png", stored_path=str(alive),
                               md5="a" * 32, size=48, content_type="image/png", recognize_status="done"),
                    Screenshot(report_id=rep.id, owner_uid="1000", partition="online_done",
                               filename="gone.png", stored_path=str(up / "gone.png"),
                               md5="b" * 32, size=48, content_type="image/png", recognize_status="done"),
                ]
            )
            db.commit()
        finally:
            db.close()

        out = self.diag._dump_screenshot_records()
        self.assertIn("截图记录 2 条", out)
        self.assertIn("原图缺失 1 条", out, "必须点出缺失数量，否则真机无法判断 410 来源")
        self.assertIn("gone.png", out)

        db = SessionLocal()
        try:
            db.query(Screenshot).delete()
            db.commit()
        finally:
            db.close()

    def test_upload_tree_counted(self):
        """上传目录要给出数量级 —— 用于判断「目录被清空」还是「数据还在」。"""
        up = self.tmp / "up2"
        (up / "a").mkdir(parents=True, exist_ok=True)
        (up / "a" / "1.png").write_bytes(b"0" * 10)
        (up / "2.png").write_bytes(b"0" * 20)
        out = self.diag._count_tree(up)
        self.assertIn("文件数 2", out)
        self.assertIn("30 bytes", out)
        empty = self.tmp / "empty_up"
        empty.mkdir(parents=True, exist_ok=True)
        self.assertIn("目录为空", self.diag._count_tree(empty))


if __name__ == "__main__":
    unittest.main()
