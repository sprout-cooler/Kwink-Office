"""v1.0.42 本地大模型接入优化 —— 回归测试。

三项用户拍板的改动：
  1. AI_PROVIDERS 增加 Ollama 本地预设（只列视觉模型，带占位 Key）；
  2. 本地/内网端点免填 API Key（前后端共用「内网」判定口径）；
  3. 单次识别超时由设置页可配，默认 60 秒、范围 30~600。

取证见 docs/本地大模型-软件接入指引.md §0：项目原本就按 OpenAI-compatible
契约实现，协议级冒烟已验证「内网 http + 任意 Key + base64 图片 + json_object」可通。
"""
from __future__ import annotations

import unittest

from app.core import settings_service as ss
from app.modules.weekly_report import vlm


class TestOllamaProviderPreset(unittest.TestCase):
    """① 服务商预设。"""

    def test_preset_exists_with_vision_models_only(self):
        p = next((x for x in ss.AI_PROVIDERS if x["id"] == "ollama"), None)
        self.assertIsNotNone(p, "应有 Ollama 预设")
        assert p is not None
        self.assertIn(":11434/v1", p["baseUrl"])
        self.assertTrue(p["baseUrl"].startswith("http://"), "内网地址必须用 http")
        self.assertTrue(p["models"], "应给出推荐模型")
        # 周报是截图识别，绝不能把纯文本模型列进预设
        for m in p["models"]:
            self.assertNotIn("deepseek", m.lower(), f"{m} 是纯文本模型")
            self.assertNotIn("embed", m.lower(), f"{m} 是向量模型")

    def test_preset_carries_placeholder_key_and_note(self):
        p = next(x for x in ss.AI_PROVIDERS if x["id"] == "ollama")
        self.assertTrue(p.get("defaultApiKey"), "应带占位 Key，省去用户手填")
        self.assertIn("视觉", p.get("note", ""), "说明里必须强调只能用视觉模型")
        self.assertTrue(p.get("modelDetails"), "应带模型说明")

    def test_custom_provider_still_exists(self):
        """保留原来的「自建兼容端点」，不能因为加预设而弄丢。"""
        self.assertTrue(any(x["id"] == "custom" for x in ss.AI_PROVIDERS))


class TestLocalEndpointNoKey(unittest.TestCase):
    """② 内网端点免 Key；公网端点仍然强制。"""

    LOCAL_URLS = (
        "http://192.168.31.182:11434/v1",
        "http://localhost:11434/v1",
        "http://127.0.0.1:1234/v1",
        "10.0.0.5:8000/v1",
        "http://172.20.1.9:8000/v1",
    )
    PUBLIC_URLS = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://ark.cn-beijing.volces.com/api/v3",
        "https://llm.example.com/v1",
    )

    def test_local_empty_key_gets_placeholder(self):
        for url in self.LOCAL_URLS:
            with self.subTest(url=url):
                self.assertEqual(
                    vlm._effective_api_key("", url), vlm.LOCAL_PLACEHOLDER_KEY
                )

    def test_public_empty_key_stays_empty(self):
        for url in self.PUBLIC_URLS:
            with self.subTest(url=url):
                self.assertEqual(vlm._effective_api_key("", url), "")

    def test_explicit_key_never_overridden(self):
        """用户自己填了 Key（哪怕在内网）就原样用，不能被占位串覆盖。"""
        self.assertEqual(
            vlm._effective_api_key("my-secret", "http://192.168.31.182:11434/v1"),
            "my-secret",
        )
        self.assertEqual(
            vlm._effective_api_key("  sk-abc  ", "https://api.example.com/v1"),
            "sk-abc",
        )

    def test_recognizer_accepts_empty_key_for_local(self):
        r = vlm.OpenAICompatibleRecognizer(
            api_key="", base_url="http://192.168.31.182:11434/v1", model="qwen2.5vl:7b"
        )
        self.assertEqual(r.api_key, vlm.LOCAL_PLACEHOLDER_KEY)
        self.assertEqual(r.base_url, "http://192.168.31.182:11434/v1")

    def test_probe_connection_allows_empty_key_on_local(self):
        """设置页「测试连接」在本地端点不应因为空 Key 直接拒绝。

        这里只验证它越过了 Key 校验（真正发请求会用不可达地址而失败），
        而不是被「API Key 为空」挡在第一步。
        """
        ok, msg = vlm.probe_connection(
            "http://127.0.0.1:1/v1", "qwen2.5vl:7b", "", timeout=2
        )
        self.assertFalse(ok)
        self.assertNotIn("API Key 为空", msg, "内网端点不应被空 Key 拦住")

    def test_probe_connection_still_rejects_empty_key_on_public(self):
        ok, msg = vlm.probe_connection(
            "https://api.example.com/v1", "some-model", "", timeout=2
        )
        self.assertFalse(ok)
        self.assertIn("API Key 为空", msg)


class TestRecognizeTimeoutSetting(unittest.TestCase):
    """③ 超时可配置。"""

    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.db.models import Base

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_default_is_60(self):
        app = ss.get_app_settings(self.db)
        self.assertEqual(app["recognize_timeout_s"]["value"], 60)

    def test_configurable_and_clamped(self):
        ss.save_app_settings(self.db, {"recognize_timeout_s": 180})
        self.db.commit()
        self.assertEqual(
            ss.get_app_settings(self.db)["recognize_timeout_s"]["value"], 180
        )
        ss.save_app_settings(self.db, {"recognize_timeout_s": 99999})
        self.db.commit()
        self.assertEqual(
            ss.get_app_settings(self.db)["recognize_timeout_s"]["value"], 600
        )
        ss.save_app_settings(self.db, {"recognize_timeout_s": 1})
        self.db.commit()
        self.assertEqual(
            ss.get_app_settings(self.db)["recognize_timeout_s"]["value"], 30
        )

    def test_recognizer_uses_custom_timeout(self):
        r = vlm.OpenAICompatibleRecognizer(
            api_key="ollama",
            base_url="http://192.168.31.182:11434/v1",
            model="qwen2.5vl:7b",
            timeout_s=300,
        )
        self.assertEqual(r.timeout_s, 300)

    def test_recognizer_default_timeout(self):
        r = vlm.OpenAICompatibleRecognizer(
            api_key="k", base_url="https://api.example.com/v1", model="m"
        )
        self.assertEqual(r.timeout_s, vlm.TIMEOUT_S)


if __name__ == "__main__":
    unittest.main()
