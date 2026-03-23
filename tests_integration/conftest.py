"""集成测试配置"""

from __future__ import annotations

import os
import pytest


def pytest_configure(config):
    """配置pytest"""
    # 设置测试环境变量
    os.environ.setdefault("FEISHU_APP_ID", "test_app_id")
    os.environ.setdefault("FEISHU_APP_SECRET", "test_app_secret")
    os.environ.setdefault("TZ", "UTC")


def pytest_unconfigure(config):
    """清理测试环境"""
    # 清理测试环境变量
    test_env_vars = [
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "DEFAULT_BACKEND",
        "AGENT_TIMEOUT",
    ]

    for var in test_env_vars:
        if var in os.environ and os.environ[var].startswith("test_"):
            del os.environ[var]


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环用于异步测试"""
    import asyncio

    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
