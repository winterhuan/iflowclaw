"""安全相关模块单元测试"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from iflowclaw.config import load_config
from iflowclaw.credential_proxy import ProxyConfig, build_proxy_config, detect_auth_mode
from iflowclaw.mount_security import (
    DEFAULT_BLOCKED_PATTERNS,
    MountValidationResult,
    _expand_path,
    _is_valid_container_path,
    _matches_blocked_pattern,
    validate_additional_mounts,
    validate_mount,
)


class TestCredentialProxy(unittest.TestCase):
    """凭证代理测试"""

    def test_detect_auth_mode_api_key(self) -> None:
        """测试 API 密钥模式检测"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"
            os.environ["ANTHROPIC_API_KEY"] = "sk-test-123"

            config = load_config(root)
            mode = detect_auth_mode(config)

            self.assertEqual(mode, "api-key")

    def test_detect_auth_mode_oauth(self) -> None:
        """测试 OAuth 模式检测"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"
            # 清除 API 密钥
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]

            config = load_config(root)
            mode = detect_auth_mode(config)

            self.assertEqual(mode, "oauth")

    def test_build_proxy_config(self) -> None:
        """测试代理配置构建"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "store").mkdir(parents=True, exist_ok=True)
            os.environ["FEISHU_APP_ID"] = "test_id"
            os.environ["FEISHU_APP_SECRET"] = "test_secret"
            os.environ["ANTHROPIC_API_KEY"] = "sk-test-123"
            os.environ["ANTHROPIC_BASE_URL"] = "https://custom.api.com"

            config = load_config(root)
            proxy_config = build_proxy_config(config)

            self.assertEqual(proxy_config.auth_mode, "api-key")
            self.assertEqual(proxy_config.api_key, "sk-test-123")
            self.assertEqual(proxy_config.upstream_url, "https://custom.api.com")

    def test_proxy_config_dataclass(self) -> None:
        """测试 ProxyConfig 数据类"""
        proxy_config = ProxyConfig(
            auth_mode="api-key",
            api_key="sk-test",
            oauth_token="oauth-token",
            upstream_url="https://api.anthropic.com",
        )

        self.assertEqual(proxy_config.auth_mode, "api-key")
        self.assertEqual(proxy_config.api_key, "sk-test")
        self.assertEqual(proxy_config.oauth_token, "oauth-token")
        self.assertEqual(proxy_config.upstream_url, "https://api.anthropic.com")


class TestMountSecurity(unittest.TestCase):
    """挂载安全测试"""

    def test_default_blocked_patterns(self) -> None:
        """测试默认阻止模式"""
        expected_patterns = [
            ".ssh",
            ".gnupg",
            ".gpg",
            ".aws",
            ".azure",
            ".gcloud",
            ".kube",
            ".docker",
            "credentials",
            ".env",
            ".netrc",
            ".npmrc",
            ".pypirc",
            "id_rsa",
            "id_ed25519",
            "private_key",
            ".secret",
        ]

        for pattern in expected_patterns:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, DEFAULT_BLOCKED_PATTERNS)

    def test_expand_path_home(self) -> None:
        """测试家目录路径展开"""
        expanded = _expand_path("~/test")
        self.assertIn("test", expanded)
        self.assertNotIn("~", expanded)

    def test_expand_path_current(self) -> None:
        """测试当前目录路径展开"""
        expanded = _expand_path(".")
        self.assertNotIn(".", expanded)

    def test_expand_path_absolute(self) -> None:
        """测试绝对路径"""
        expanded = _expand_path("/tmp/test")
        # Windows 上会解析为完整路径，Linux/Mac 保持原样
        normalized = "tmp" + os.sep + "test"
        self.assertTrue(
            expanded.endswith(normalized) or expanded.endswith("/tmp/test") or "tmp" in expanded
        )

    def test_is_valid_container_path(self) -> None:
        """测试容器路径验证"""
        # 有效路径
        self.assertTrue(_is_valid_container_path("workspace"))
        self.assertTrue(_is_valid_container_path("data/files"))
        self.assertTrue(_is_valid_container_path("my-folder"))

        # 无效路径
        self.assertFalse(_is_valid_container_path(".."))
        self.assertFalse(_is_valid_container_path("/absolute"))
        self.assertFalse(_is_valid_container_path(""))
        self.assertFalse(_is_valid_container_path("  "))

    def test_matches_blocked_pattern(self) -> None:
        """测试阻止模式匹配"""
        blocked_patterns = [".ssh", ".aws", "credentials"]

        # 应该匹配的路径（使用 os.path.normpath 适配 Windows）
        self.assertIsNotNone(_matches_blocked_pattern(os.path.normpath("/home/user/.ssh"), blocked_patterns))
        self.assertIsNotNone(_matches_blocked_pattern(os.path.normpath("/home/user/.aws/config"), blocked_patterns))
        self.assertIsNotNone(_matches_blocked_pattern(os.path.normpath("/path/to/credentials"), blocked_patterns))

        # 不应该匹配的路径
        self.assertIsNone(_matches_blocked_pattern(os.path.normpath("/home/user/documents"), blocked_patterns))
        self.assertIsNone(_matches_blocked_pattern(os.path.normpath("/tmp/test"), blocked_patterns))

    def test_matches_blocked_pattern_with_extension(self) -> None:
        """测试带扩展名的阻止模式"""
        blocked_patterns = [".env"]

        # 应该匹配（使用 os.path.normpath 适配 Windows）
        self.assertIsNotNone(_matches_blocked_pattern(os.path.normpath("/path/to/.env"), blocked_patterns))
        self.assertIsNotNone(_matches_blocked_pattern(os.path.normpath("/path/to/.env.local"), blocked_patterns))

        # 不应该匹配
        self.assertIsNone(_matches_blocked_pattern(os.path.normpath("/path/to/environment"), blocked_patterns))

    def test_mount_validation_result(self) -> None:
        """测试挂载验证结果"""
        result = MountValidationResult(
            allowed=True,
            reason="Allowed",
            real_host_path="/host/path",
            resolved_container_path="container/path",
            effective_readonly=True,
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "Allowed")
        self.assertEqual(result.real_host_path, "/host/path")
        self.assertEqual(result.resolved_container_path, "container/path")
        self.assertTrue(result.effective_readonly)


class TestValidateMount(unittest.TestCase):
    """挂载验证测试"""

    def test_validate_mount_no_allowlist(self) -> None:
        """测试没有允许列表时的验证"""
        # 清除缓存
        import iflowclaw.mount_security as ms

        ms._cached_allowlist = None
        ms._allowlist_load_error = None

        result = validate_mount("/tmp/test", "test", False, False)

        self.assertFalse(result.allowed)
        self.assertIn("No mount allowlist", result.reason)

    def test_validate_mount_invalid_container_path(self) -> None:
        """测试无效容器路径"""
        import iflowclaw.mount_security as ms

        # 创建临时允许列表
        with tempfile.TemporaryDirectory() as td:
            allowlist_path = Path(td) / "mount-allowlist.json"
            allowlist_path.write_text(
                json.dumps(
                    {
                        "allowedRoots": [{"path": str(Path(td))}],
                        "blockedPatterns": [],
                        "nonMainReadOnly": True,
                    }
                ),
                encoding="utf-8",
            )

            # 重置缓存并加载新的允许列表
            ms._cached_allowlist = None
            ms._allowlist_load_error = None
            ms.load_mount_allowlist(allowlist_path)

            result = validate_mount(str(Path(td) / "test"), "../invalid", False, False)

            self.assertFalse(result.allowed)
            self.assertIn("Invalid container path", result.reason)


class TestValidateAdditionalMounts(unittest.TestCase):
    """额外挂载验证测试"""

    def test_validate_additional_mounts_empty(self) -> None:
        """测试空挂载列表"""
        result = validate_additional_mounts([], "test_group", False)
        self.assertEqual(result, [])

    def test_validate_additional_mounts_format(self) -> None:
        """测试挂载格式"""
        mounts = [
            {
                "hostPath": "/tmp/test",
                "containerPath": "test",
                "readonly": True,
            }
        ]

        # 由于没有允许列表，应该返回空
        result = validate_additional_mounts(mounts, "test_group", False)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
