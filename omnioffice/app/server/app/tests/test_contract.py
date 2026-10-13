"""依赖与配置完整性测试（避坑指南 §1.7 / §1.9 / §1.10）。

为什么需要这个文件：
本项目本地开发跑 SQLite，永远不会触发 SQLAlchemy 的 PG 方言 `import_dbapi`，
所以「本地全绿、真机 Bad Gateway」曾反复发生（v1.0.5）。§1.9 明确要求：
**任何数据库相关依赖/连接串变更，必须有能验证 PG 方言导入的本地检查**。

这里用「导入断言 + 依赖声明断言」把该红线固化，成本极低但能在打包前拦截。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

# server/app/tests/test_contract.py → server/ 是 package_root 的 parent.parent.parent
SERVER_ROOT = Path(__file__).resolve().parent.parent.parent  # server/
# docker/ 与 Dockerfile.api 位于 app/docker/（与 server/ 同级）
APP_ROOT = SERVER_ROOT.parent                              # app/
PKG_ROOT = APP_ROOT.parent                                  # omnioffice/（包根）

REQ = SERVER_ROOT / "requirements.txt"
DOCKERFILE = APP_ROOT / "docker" / "Dockerfile.api"
COMPOSE = APP_ROOT / "docker" / "docker-compose.yaml"
MAIN_PY = SERVER_ROOT / "app" / "main.py"

# 测试用的业务空间 ID 占位串。真实 WorkspaceId 属个人凭证信息，
# 一律不得写入源码 —— 见 TestSettingsLayering.test_no_personal_workspace_id_hardcoded。
WORKSPACE_ID = "llm-WORKSPACEIDPLACEHOLDER"


def _req_text() -> str:
    return REQ.read_text(encoding="utf-8") if REQ.is_file() else ""


class TestPostgresDriverRedline(unittest.TestCase):
    """§1.9 SQLAlchemy 2.0 默认方言是 psycopg3，不是 psycopg2。"""

    def test_requirements_declares_psycopg3(self):
        text = _req_text()
        self.assertRegex(
            text,
            r"(?m)^psycopg(?:\[binary\])?\s*[><=!~]",
            "requirements 必须声明 psycopg[binary]（SQLAlchemy 2.0 的 PG 默认驱动）",
        )

    def test_requirements_must_not_use_psycopg2(self):
        text = _req_text()
        self.assertNotRegex(
            text,
            r"(?m)^psycopg2-binary",
            "psycopg2-binary 不会被 postgresql:// 默认 URL 使用，真机必崩 ModuleNotFoundError: psycopg",
        )

    def test_pg_dialect_importable(self):
        """能真正 import psycopg 方言 —— 缺包时立刻暴露，而不是等真机。"""
        try:
            from sqlalchemy.dialects.postgresql import psycopg as pg_psycopg  # noqa: F401
        except ImportError as e:  # pragma: no cover - 依赖缺失时的失败路径
            self.fail(
                f"无法导入 SQLAlchemy PG 方言（{e}）。真机将 Bad Gateway。"
                f"请确认已安装 psycopg[binary]。"
            )


class TestContainerRuntimeRedlines(unittest.TestCase):
    """§1.7 / §1.8 / §1.10 容器与打包红线（静态检查，无需 Docker）。"""

    @classmethod
    def setUpClass(cls):
        cls.dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        cls.compose = COMPOSE.read_text(encoding="utf-8")
        cls.main_py = MAIN_PY.read_text(encoding="utf-8")

    def test_media_types_installed(self):
        """§1.7：slim 镜像缺 /etc/mime.types 会让 .js 被当 octet-stream → 白屏。"""
        self.assertRegex(
            self.dockerfile,
            r"media-types",
            "Dockerfile.api 必须安装 media-types（§1.7，否则真机 .js MIME 错误白屏）",
        )

    def test_explicit_mime_map_in_server(self):
        """§1.7 双保险：服务端维护显式 MIME 映射，不依赖宿主 mime.types。"""
        self.assertIn("_MIME", self.main_py, "main.py 缺少显式 MIME 映射表（§1.7）")
        for ext in ('".js"', '".css"', '".json"'):
            self.assertIn(ext, self.main_py, f"显式 MIME 映射缺少 {ext}")

    def test_base_image_switchable(self):
        """§1.8：基础镜像留 ARG 口子，便于切国内镜像站。"""
        self.assertRegex(self.dockerfile, r"ARG\s+BASE_IMAGE", "Dockerfile.api 应留 ARG BASE_IMAGE 切换口")

    def test_postgres_healthcheck_and_condition(self):
        """§1.10 第一层：healthcheck + condition: service_healthy。"""
        self.assertIn("healthcheck", self.compose, "postgres 缺 healthcheck（§1.10）")
        self.assertIn("pg_isready", self.compose, "healthcheck 应用 pg_isready 探活")
        self.assertIn(
            "service_healthy",
            self.compose,
            "api/worker 应用 condition: service_healthy（§1.10，depends_on 不等于服务可用）",
        )

    def test_gateway_prefix_dual_mount(self):
        """§1.2 / Agent 指南案例 5：API 必须双前缀挂载，否则网关下 404 被 SPA 吞成 HTML。"""
        self.assertIn(
            f'prefix=f"{{settings.gateway_prefix}}/api"',
            self.main_py,
            "main.py 缺少网关前缀的 API 双挂载（§1.2）",
        )

    def test_static_path_strips_gateway_prefix(self):
        """§1.6：静态查找前必须剥前缀，否则带前缀请求被 SPA 兜底吞成 HTML → 白屏。"""
        self.assertIn(
            'rel[len(prefix) + 1 :]',
            self.main_py,
            "spa() 未剥离网关前缀（§1.6，真机白屏头号原因）",
        )

    def test_dir_traversal_guard(self):
        """§3.1 / V10 8.12：拒绝 .. 目录穿越。"""
        self.assertRegex(
            self.main_py,
            r"startswith\(str\(root\)\)",
            "静态服务缺少目录穿越防护（§3.1）",
        )


class TestSettingsLayering(unittest.TestCase):
    """AI 配置三层优先级（模块覆盖 > 全局 > 环境变量 > 内置兜底）。

    这是设置页「不同模块配不同模型」的核心逻辑，必须有单测防止回归。
    """

    def setUp(self):
        from app.core import settings_service as ss
        from app.db.models import Setting
        from app.db.session import SessionLocal, init_db

        init_db()
        self.ss = ss
        self.db = SessionLocal()
        for row in self.db.query(Setting).all():
            self.db.delete(row)
        self.db.commit()

    def tearDown(self):
        from app.db.models import Setting

        for row in self.db.query(Setting).all():
            self.db.delete(row)
        self.db.commit()
        self.db.close()

    def test_builtin_default_when_nothing_configured(self):
        """全空时必须有可用兜底，UI 不能空白。"""
        cfg = self.ss.resolve_ai(self.db)
        self.assertTrue(cfg["base_url"], "兜底 base_url 为空")
        self.assertTrue(cfg["model"], "兜底 model 为空")
        self.assertEqual(cfg["api_key"], "")

    def test_global_applies_to_all_modules(self):
        self.ss.save_ai_config(self.db, {"api_key": "sk-global-1234567890", "model": "g"}, None)
        self.db.commit()
        cfg = self.ss.resolve_ai(self.db, "any_module")
        self.assertEqual(cfg["api_key"], "sk-global-1234567890")
        self.assertEqual(cfg["model"], "g")

    def test_module_overrides_global(self):
        self.ss.save_ai_config(self.db, {"api_key": "sk-global-1234567890", "model": "g"}, None)
        self.ss.save_ai_config(self.db, {"model": "m", "api_key": "sk-module-9999999"}, "weekly_report")
        self.db.commit()
        cfg = self.ss.resolve_ai(self.db, "weekly_report")
        self.assertEqual(cfg["model"], "m", "模块应覆盖全局 model")
        self.assertEqual(cfg["api_key"], "sk-module-9999999", "模块应覆盖全局 Key")
        # 其他模块不受影响
        self.assertEqual(self.ss.resolve_ai(self.db, "other")["model"], "g")

    def test_partial_override_inherits_remaining_fields(self):
        """只覆盖 model 时，base_url/key 仍应继承全局（部分覆盖语义）。"""
        self.ss.save_ai_config(self.db, {"base_url": "https://global/v1", "api_key": "sk-global-1234567890"}, None)
        self.ss.save_ai_config(self.db, {"model": "only-model"}, "weekly_report")
        self.db.commit()
        cfg = self.ss.resolve_ai(self.db, "weekly_report")
        self.assertEqual(cfg["model"], "only-model")
        self.assertEqual(cfg["base_url"], "https://global/v1", "base_url 应继承全局")
        self.assertEqual(cfg["api_key"], "sk-global-1234567890", "api_key 应继承全局")

    def test_reset_module_restores_inheritance(self):
        self.ss.save_ai_config(self.db, {"model": "g"}, None)
        self.ss.save_ai_config(self.db, {"model": "m"}, "weekly_report")
        self.db.commit()
        self.ss.reset_module_ai(self.db, "weekly_report")
        self.db.commit()
        self.assertEqual(self.ss.resolve_ai(self.db, "weekly_report")["model"], "g")
        self.assertFalse(self.ss.get_ai_config(self.db, "weekly_report")["overridden"])

    def test_empty_string_clears_single_field_override(self):
        """前端「恢复继承全局」按钮：空字符串 = 只清该字段。"""
        self.ss.save_ai_config(self.db, {"model": "g", "api_key": "sk-global-1234567890"}, None)
        self.ss.save_ai_config(self.db, {"model": "m"}, "weekly_report")
        self.db.commit()
        self.ss.save_ai_config(self.db, {"model": ""}, "weekly_report")
        self.db.commit()
        cfg = self.ss.resolve_ai(self.db, "weekly_report")
        self.assertEqual(cfg["model"], "g", "清空后应回到全局")
        self.assertEqual(cfg["api_key"], "sk-global-1234567890", "其他字段覆盖不应被误清")

    def test_api_key_never_returned_in_plaintext(self):
        """§3.2 安全：前端视图只给 has_key / masked。"""
        self.ss.save_ai_config(self.db, {"api_key": "sk-secret-abcdef123456"}, None)
        self.db.commit()
        view = self.ss.get_ai_config(self.db)
        self.assertNotIn("api_key", view)
        self.assertTrue(view["has_key"])
        self.assertNotIn("sk-secret", str(view), "脱敏视图泄露了 Key 明文")

    def test_registered_modules_always_listed(self):
        """注册表里的模块必须都出现在设置页（否则用户看不到可配置项）。"""
        from app.modules import registry

        payload = self.ss.get_all_settings(self.db, registry.list_enabled())
        ids = [m["id"] for m in payload["ai_modules"]]
        self.assertIn("weekly_report", ids)

    def test_wizard_custom_workspace_domain_wins(self):
        """百炼业务空间专属域名优先于下拉选中的 DashScope 通用域名。

        背景：阿里云把接入分为「DashScope 通用域名」与「业务空间专属域名」，
        后者并发更高、超时 3600 秒，且通用域名自 2026-09-30 起不再支持新特性。
        用户在向导里填了专属地址时必须以其为准。

        注意：此处一律用 WORKSPACE 占位串，禁止写入真实 WorkspaceId
        （个人专属地址硬编码会让其他用户装上就连错，见下方红线测试）。
        """
        workspace_url = f"https://{WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        self.ss.inject_wizard_defaults(
            self.db,
            {
                "llm_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "llm_base_url_custom": workspace_url,
                "llm_api_key": "sk-test-1234567890",
            },
        )
        self.db.commit()
        self.assertEqual(
            self.ss.resolve_ai(self.db)["base_url"],
            workspace_url,
            "专属域名应覆盖通用域名",
        )

    def test_wizard_falls_back_when_custom_empty(self):
        """未填专属域名时，沿用下拉选择的地址。"""
        self.ss.inject_wizard_defaults(
            self.db,
            {
                "llm_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "llm_base_url_custom": "",
            },
        )
        self.db.commit()
        self.assertEqual(
            self.ss.resolve_ai(self.db)["base_url"],
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def test_workspace_domain_provider_preset_exists(self):
        """设置页必须提供「业务空间专属域名」预设项，且带填写模板。

        WorkspaceId 因人而异，不能硬编码进默认值，只能作为占位模板提供。
        """
        qwen_ws = next((p for p in self.ss.AI_PROVIDERS if p["id"] == "qwen_workspace"), None)
        self.assertIsNotNone(qwen_ws, "缺少 qwen_workspace 预设项")
        self.assertEqual(qwen_ws["baseUrl"], "", "专属域名预设不得硬编码具体 WorkspaceId")
        self.assertIn("{WorkspaceId}", qwen_ws.get("placeholder", ""), "预设应提供 WorkspaceId 占位模板")

    def test_provider_presets_single_source(self):
        """vlm.PROVIDER_PRESETS 必须引用 settings_service.AI_PROVIDERS（避免两处各存一份漏改）。"""
        from app.modules.weekly_report import vlm

        self.assertEqual(
            [p["id"] for p in vlm.PROVIDER_PRESETS],
            [p["id"] for p in self.ss.AI_PROVIDERS],
            "vlm.PROVIDER_PRESETS 与 settings_service.AI_PROVIDERS 不一致（曾因各存一份导致漏改）",
        )

    def test_no_personal_workspace_id_hardcoded(self):
        """红线：不得把某个用户的业务空间 ID 写进运行时代码。

        个人 WorkspaceId 硬编码会让其他用户装上后直接连错地址。
        只扫运行时源码（排除本测试文件——它必须含样例域名才能验证逻辑）。
        """
        import re

        pattern = re.compile(r"https://llm-(?!WORKSPACEIDPLACEHOLDER)[a-z0-9]{8,}\.", re.I)
        offenders = []
        for py in SERVER_ROOT.rglob("*.py"):
            if "__pycache__" in py.parts or py.name == Path(__file__).name:
                continue
            if pattern.search(py.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(py.relative_to(SERVER_ROOT)))
        self.assertEqual(offenders, [], f"运行时代码中硬编码了个人业务空间域名：{offenders}")

    def test_workspace_domain_regex_contract(self):
        """前端专属域名识别正则的行为契约（与 AiConfigForm.vue 保持同构）。

        背景：原正则漏了 https:// 前缀，导致**用户自己的专属域名也识别不出来**，
        服务商下拉会误落到「自建兼容端点」。此处固化行为，防再次回归。
        """
        import re

        # 与 web/src/shell/AiConfigForm.vue 的 WORKSPACE_DOMAIN_RE 同构
        pattern = re.compile(r"^(?:https?://)?[a-z0-9-]+\.[a-z0-9-]+\.maas\.aliyuncs\.com(?:/|$)", re.I)

        should_match = [
            "https://llm-workspaceidplaceholder.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "http://llm-abc.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
            "https://llm-abc.cn-beijing.maas.aliyuncs.com",
            "https://llm-abc.cn-beijing.maas.aliyuncs.com/apps/anthropic",
        ]
        should_not_match = [
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://ark.cn-beijing.volces.com/api/v3",
            # 后缀伪造：结尾不是 .maas.aliyuncs.com 也不是 /
            "https://llm-abc.cn-beijing.maas.aliyuncs.com.attacker.com/v1",
            "https://maas.aliyuncs.com.evil.net/v1",
        ]
        for u in should_match:
            self.assertTrue(pattern.match(u), f"应识别为专属域名：{u}")
        for u in should_not_match:
            self.assertIsNone(pattern.match(u), f"不应识别为专属域名：{u}")

    def test_default_model_is_not_legacy(self):
        """默认模型不得是百炼已从推荐列表移除的 qwen-vl-*（2026-10 官方现状）。

        背景：内置默认值曾是 qwen-vl-max，该模型已下线/不再推荐，新装用户
        会直接踩空。默认必须是现役且支持 JSON 结构化输出的 qwen3 系列。
        """
        legacy = {"qwen-vl-max", "qwen-vl-plus"}
        self.assertNotIn(
            self.ss.BUILTIN_DEFAULTS["model"],
            legacy,
            "默认模型不得为已下线的 qwen-vl-* 系列",
        )
        self.assertTrue(
            self.ss.BUILTIN_DEFAULTS["model"].startswith("qwen3"),
            f"默认模型应为 qwen3 系列，当前={self.ss.BUILTIN_DEFAULTS['model']}",
        )

    def test_model_list_covers_weekly_report_needs(self):
        """模型清单必须覆盖周报场景的三个档位，且推荐档排在最前。

        周报识别要求：图像输入 + JSON 结构化输出 + 成本可权衡（省钱/高能）。
        """
        details = {m["id"]: m for m in self.ss.QWEN_MODELS}
        self.assertEqual(
            self.ss.QWEN_MODEL_OPTIONS[0],
            "qwen3.8-flash",
            "推荐档应排在模型下拉第一位",
        )
        # 官方 2026-10-11 视觉模型页的现役主力，缺一则用户只能选到旧版（会 404）
        for required in ("qwen3.8-flash", "qwen3.8-max"):
            self.assertIn(required, details, f"缺少模型 {required}")
        # 每项都要有说明与合法 tier（前端据此渲染角标）
        valid_tiers = {"recommended", "economy", "stable", "strong", "special", "legacy"}
        for mid, d in details.items():
            self.assertTrue(d.get("desc"), f"{mid} 缺少场景说明")
            self.assertIn(d.get("tier"), valid_tiers, f"{mid} 的 tier 非法：{d.get('tier')}")
        # 省钱档与高能档至少各有一个，兼顾成本与准确率
        tiers = {d["tier"] for d in self.ss.QWEN_MODELS}
        self.assertIn("economy", tiers, "缺少省钱档模型")
        self.assertIn("strong", tiers, "缺少高能力档模型")

    def test_legacy_models_marked_not_recommended(self):
        """旧版模型若保留（兼容存量配置），必须标记为 legacy 以便前端警示。

        qwen3-vl-* 同样归入旧版：官方 2026-10-11 视觉模型页已不作为首选推荐，
        qwen3-vl-flash 甚至不在列表中，调用会 404。
        """
        for mid in ("qwen-vl-max", "qwen-vl-plus", "qwen3-vl-plus", "qwen3-vl-flash"):
            d = next((m for m in self.ss.QWEN_MODELS if m["id"] == mid), None)
            if d is None:
                continue
            self.assertEqual(d["tier"], "legacy", f"{mid} 应标记为 legacy")
            self.assertIn("旧版", d["label"], f"{mid} 标签应含「旧版」")

    def test_providers_expose_model_details(self):
        """百炼类服务商必须带 modelDetails，供前端渲染说明与档位角标。"""
        for p in self.ss.AI_PROVIDERS:
            # 所有百炼类预设（通用域名各地域 + 业务空间专属域名）都要带清单
            if p["id"].startswith("qwen"):
                self.assertTrue(p.get("modelDetails"), f"{p['id']} 缺少 modelDetails")
                self.assertEqual(p["models"], self.ss.QWEN_MODEL_OPTIONS, f"{p['id']} models 应与清单一致")

    def test_recognizer_sends_response_format(self):
        """识别请求应带 response_format=json_object（qwen3 结构化输出能力）。"""
        vlm_src = (SERVER_ROOT / "app" / "modules" / "weekly_report" / "vlm.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"response_format"', vlm_src, "识别请求未启用 response_format")
        self.assertIn('"type": "json_object"', vlm_src, "response_format 类型应为 json_object")

    def test_recognizer_degrades_on_400(self):
        """端点不支持 response_format 时应降级重试，而不是直接失败。"""
        vlm_src = (SERVER_ROOT / "app" / "modules" / "weekly_report" / "vlm.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("http_code", vlm_src, "错误对象应带 http_code 供降级判断")
        self.assertIn("self.json_mode = False", vlm_src, "400 后应关闭 json_mode 并重试")

    def test_app_settings_clamped_to_range(self):
        """应用级配置必须做范围裁剪，防越界值。"""
        self.ss.save_app_settings(self.db, {"recognize_workers": 999, "upload_max_mb": 0})
        self.db.commit()
        app = self.ss.get_app_settings(self.db)
        self.assertLessEqual(app["recognize_workers"]["value"], 8)
        self.assertGreaterEqual(app["upload_max_mb"]["value"], 1)

    def test_unknown_app_keys_ignored(self):
        """白名单外的键不得写入 settings 表。"""
        self.ss.save_app_settings(self.db, {"evil_key": 1})
        self.db.commit()
        self.assertNotIn("evil_key", self.ss.get_app_settings(self.db))


class TestWizardInjection(unittest.TestCase):
    """向导注入只补空缺，不覆盖用户在设置页的修改。"""

    def setUp(self):
        from app.db.models import Setting
        from app.db.session import SessionLocal, init_db

        init_db()
        self.db = SessionLocal()
        for row in self.db.query(Setting).all():
            self.db.delete(row)
        self.db.commit()

    def tearDown(self):
        from app.db.models import Setting

        for row in self.db.query(Setting).all():
            self.db.delete(row)
        self.db.commit()
        self.db.close()

    def test_wizard_fills_empty_only(self):
        from app.core import settings_service as ss

        ss.inject_wizard_defaults(self.db, {"llm_api_key": "sk-wizard-1234567890"})
        self.db.commit()
        self.assertEqual(ss.resolve_ai(self.db)["api_key"], "sk-wizard-1234567890")

        # 用户在设置页改过之后，重启（再次注入）不应覆盖
        ss.save_ai_config(self.db, {"api_key": "sk-user-changed-999"}, None)
        self.db.commit()
        ss.inject_wizard_defaults(self.db, {"llm_api_key": "sk-wizard-1234567890"})
        self.db.commit()
        self.assertEqual(ss.resolve_ai(self.db)["api_key"], "sk-user-changed-999")


if __name__ == "__main__":
    unittest.main()
