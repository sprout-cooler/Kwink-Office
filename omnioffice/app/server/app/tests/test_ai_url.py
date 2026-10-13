"""AI 服务地址「协议头自动补全」的边界测试。

背景：用户填写服务地址时常漏写 http(s):// 前缀，而 urllib.request 遇到无 scheme
的地址会直接抛 ``ValueError: unknown url type``。项目在多处（保存 / 读取 / 连通性
探测 / 识别请求）都会做补全，因此必须保证：

1. **仅在既无 http:// 也无 https:// 时才补全**；已带协议的原样返回；
2. 带端口、带路径、IPv4/IPv6、localhost 都能正确识别主机；
3. **幂等** —— 后端不止一处调用，重复调用绝不能拼出 https://https://；
4. 本地回环 / 内网地址补 http://（自建服务多为明文 HTTP），公网补 https://。

早期这三处各自定义了一份实现且无测试，规则一改极易漏改，故在此固化红线。
"""
from __future__ import annotations

import unittest

# run_tests.py 把 server/ 加入 sys.path，测试统一用绝对导入（见 test_contract.py）
from app.core import settings_service


class EnsureUrlSchemeTest(unittest.TestCase):
    def test_empty_and_blank_unchanged(self):
        """空值不得被补成 'https://'。"""
        self.assertEqual(settings_service.ensure_url_scheme(""), "")
        self.assertEqual(settings_service.ensure_url_scheme("   "), "")

    def test_existing_scheme_unchanged(self):
        """已带协议的地址原样返回，绝不二次拼接。"""
        for u in (
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "http://localhost:11434/v1",
            "http://192.168.1.10:8000/v1",
            "https://llm-abc.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        ):
            self.assertEqual(settings_service.ensure_url_scheme(u), u, u)

    def test_bare_domain_gets_https(self):
        self.assertEqual(
            settings_service.ensure_url_scheme("dashscope.aliyuncs.com/compatible-mode/v1"),
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def test_domain_with_port_and_path_gets_https(self):
        self.assertEqual(
            settings_service.ensure_url_scheme("api.example.com:8080/v1"),
            "https://api.example.com:8080/v1",
        )
        self.assertEqual(settings_service.ensure_url_scheme("example.com/v1"), "https://example.com/v1")

    def test_localhost_gets_http(self):
        """本地自建服务（Ollama/LocalAI）是明文 HTTP，补 https 必然 SSL 握手失败。"""
        self.assertEqual(settings_service.ensure_url_scheme("localhost"), "http://localhost")
        self.assertEqual(settings_service.ensure_url_scheme("localhost:11434/v1"), "http://localhost:11434/v1")

    def test_private_ip_gets_http(self):
        for host in (
            "127.0.0.1:8000/v1",
            "10.0.0.5:8080",
            "172.16.0.9:1234",
            "172.31.255.1",
            "192.168.1.10:8000/v1",
            "169.254.1.1",
        ):
            self.assertTrue(
                settings_service.ensure_url_scheme(host).startswith("http://"),
                f"内网地址应补 http://：{host} -> {settings_service.ensure_url_scheme(host)}",
            )

    def test_public_ip_gets_https(self):
        self.assertEqual(settings_service.ensure_url_scheme("1.2.3.4:9000/v1"), "https://1.2.3.4:9000/v1")

    def test_ipv6_local_gets_http(self):
        self.assertEqual(settings_service.ensure_url_scheme("[::1]:8080/v1"), "http://[::1]:8080/v1")
        self.assertTrue(settings_service.ensure_url_scheme("::1:8080/v1").startswith("http://"))

    def test_surrounding_whitespace_trimmed(self):
        self.assertEqual(settings_service.ensure_url_scheme("  example.com/v1  "), "https://example.com/v1")

    def test_idempotent_no_double_prefix(self):
        """多处依次补全不得叠加协议头。"""
        for raw in (
            "example.com/v1",
            "localhost:11434/v1",
            "192.168.1.5:8000",
            "https://a.com/v1",
            "http://b.com/v1",
            "[::1]:8080/v1",
        ):
            once = settings_service.ensure_url_scheme(raw)
            twice = settings_service.ensure_url_scheme(once)
            self.assertEqual(once, twice, f"非幂等：{raw} -> {once} -> {twice}")
            self.assertNotIn("https://https://", twice, raw)
            self.assertNotIn("http://http://", twice, raw)
            self.assertNotIn("https://http://", twice, raw)
            self.assertNotIn("http://https://", twice, raw)

    def test_save_then_resolve_is_idempotent(self):
        """保存时补全一次、读取时再补全一次，结果必须与单次一致（不会重复拼接）。"""
        raw = "dashscope.aliyuncs.com/compatible-mode/v1"
        once = settings_service.ensure_url_scheme(raw)
        # 模拟「保存落库（已补全）→ 读取时再次补全」的真实链路
        self.assertEqual(settings_service.ensure_url_scheme(once), once)

    def test_vlm_reuses_shared_implementation(self):
        """vlm 必须复用 settings_service 的统一实现，防止两处规则漂移。"""
        from app.modules.weekly_report import vlm

        self.assertIs(vlm.ensure_url_scheme, settings_service.ensure_url_scheme)


if __name__ == "__main__":
    unittest.main()
