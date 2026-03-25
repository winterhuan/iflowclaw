# 集成测试说明

`tests_integration/` 用来放比 `tests/` 更接近真实运行链路的验证，但当前这些测试里，只有一部分会真正触达外部依赖或容器环境。

## 当前定位

这组测试的目标是补充以下方面的验证：

- AgentRunner 的后端选择与执行模式选择
- 多后端配置对象是否能正确构造
- MCP 环境变量与工具列表是否与当前实现一致
- 容器入口和容器后端的基础装配逻辑
- 凭证代理配置的基础行为

注意：

- 这些测试并不等同于完整端到端测试。
- 当前大部分用例仍属于“结构集成测试”或“配置集成测试”。
- 真正依赖容器、真实 SDK、真实凭证的路径覆盖还比较有限。

## 目录

```text
tests_integration/
├── conftest.py
├── test_basic.py
├── test_multi_backend.py
└── README.md
```

## 与默认 pytest 的关系

当前 `pyproject.toml` 只把 `tests/` 设为默认测试目录。

这意味着：

- 直接运行 `pytest` 时，默认不会执行 `tests_integration/`
- 需要显式指定目录或文件

## 运行方式

运行全部集成测试：

```bash
pytest tests_integration/ -v
```

或：

```bash
python -m pytest tests_integration/ -v
```

只运行基础集成测试：

```bash
pytest tests_integration/test_basic.py -v
```

只运行多后端相关测试：

```bash
pytest tests_integration/test_multi_backend.py -v
```

## 当前测试内容

### `test_basic.py`

当前主要验证：

- `AgentRunner`、`AgentConfig`、`BackendContext`、`BackendResult` 基础构造
- `_resolve_execution_mode()` 的当前行为
- `load_config()` 的基础加载逻辑

特点：

- 不依赖真实后端
- 不访问真实 Feishu
- 更接近“轻量集成测试”

### `test_multi_backend.py`

当前主要验证：

- `_BACKEND_MAP` 和默认模型映射是否完整
- 多后端配置与执行模式解析
- MCP 工具列表与环境变量构造
- `credential_proxy` 的基础配置行为
- `container_entry.build_config()` 的配置生成

特点：

- 大量用例仍然是在校验配置和装配结果
- 不是每个测试都会真正运行 Agent SDK
- 容器相关用例默认不会执行

## 容器测试

容器测试默认通过 `RUN_CONTAINER_TESTS` 开关控制：

```bash
RUN_CONTAINER_TESTS=1 pytest tests_integration/test_multi_backend.py::TestContainerBackend -v
```

前提：

- Docker 或 Podman 可用
- 已构建或可拉起对应容器镜像
- 当前主机环境允许容器运行

注意：

- 现有容器测试覆盖仍偏基础
- 容器链路本身在当前代码里仍应视为实验性能力

## 真实后端测试

如果要用真实后端做验证，需要额外准备对应凭证和模型配置。

### Claude

```bash
export ANTHROPIC_API_KEY="..."
export CLAUDE_MODEL="..."
pytest tests_integration/test_multi_backend.py -v -k "claude"
```

### iFlow

当前代码中的 `iflow` 路径依赖 Python SDK 与相应模型配置。若走 OpenAI 兼容配置，还需要：

```bash
export OPENAI_API_KEY="..."
export IFLOW_MODEL="..."
pytest tests_integration/test_multi_backend.py -v -k "iflow"
```

### Agno

```bash
export OPENAI_API_KEY="..."
export AGNO_MODEL="openai:gpt-4o"
pytest tests_integration/test_multi_backend.py -v -k "agno"
```

说明：

- 这些命令表示“如何准备环境”，不代表当前测试已经对真实后端做了充分覆盖。
- 运行真实后端前，建议先确认对应 optional dependency 已安装。

## 当前局限

这组测试目前还存在几个明显边界：

- 默认不会自动执行
- 不足以证明飞书消息链路端到端可用
- 不足以证明 IPC 权限边界完全正确
- 不足以证明容器执行模式已经稳定
- 对数据库、调度器、消息恢复等真实运行路径覆盖仍不深

## 建议使用方式

推荐按下面顺序使用：

1. 先跑 `tests/`，确保单元层无回归。
2. 再显式跑 `tests_integration/`，确认后端装配和配置层没坏。
3. 需要验证真实行为时，再单独跑容器或真实凭证相关测试。

## 后续补强方向

如果继续完善这组测试，优先级建议是：

1. 增加 `cli.py` 主循环的可控集成测试。
2. 增加 `ipc.py` 的权限与任务管理真实链路测试。
3. 增加 `group_queue.py` 与容器后续消息注入链路测试。
4. 增加调度器与任务运行日志的真实集成测试。
