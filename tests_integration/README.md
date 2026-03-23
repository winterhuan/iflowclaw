# 集成测试说明

## 概述

集成测试目录包含可以真实运行的测试，用于验证：
1. 多个agent后端的正确配置和运行
2. 直连模式和容器模式的切换
3. 容器内凭证代理的正确工作
4. MCP工具的正确桥接

## 运行测试

### 基本测试（不依赖真实凭证）

```bash
# 运行所有集成测试
pytest tests_integration/ -v

# 运行基本测试
pytest tests_integration/test_basic.py -v

# 运行多后端测试
pytest tests_integration/test_multi_backend.py -v
```

### 容器测试

容器测试需要Docker/Podman可用，并且需要设置环境变量：

```bash
# 运行容器测试
RUN_CONTAINER_TESTS=1 pytest tests_integration/test_multi_backend.py::TestContainerBackend -v
```

### 真实后端测试

要测试真实的后端，需要设置相应的环境变量：

#### iFlow后端
```bash
# 确保iFlow CLI已安装并登录
export IFLOW_MODEL="gpt-4"
pytest tests_integration/test_multi_backend.py -v -k "iflow"
```

#### Claude后端
```bash
# 设置Anthropic API密钥
export ANTHROPIC_API_KEY="sk-ant-..."
export CLAUDE_MODEL="claude-3-sonnet-20240229"
pytest tests_integration/test_multi_backend.py -v -k "claude"
```

#### Agno后端
```bash
# 设置OpenAI API密钥
export OPENAI_API_KEY="sk-..."
export AGNO_MODEL="gpt-4"
pytest tests_integration/test_multi_backend.py -v -k "agno"
```

## 测试结构

```
tests_integration/
├── conftest.py           # 测试配置
├── test_basic.py         # 基本测试（不依赖真实凭证）
├── test_multi_backend.py # 多后端集成测试
└── README.md            # 本文件
```

## 测试覆盖

### test_basic.py
- AgentRunner创建测试
- BackendContext创建测试
- AgentConfig创建测试
- BackendResult创建测试
- 执行模式解析测试
- 配置加载测试

### test_multi_backend.py
- 后端配置测试
- 执行模式解析测试
- 容器后端测试
- Agent运行器测试
- MCP集成测试
- 凭证代理测试
- 容器入口测试
- 端到端工作流测试

## 注意事项

1. **凭证安全**：不要在测试中提交真实的API密钥
2. **容器测试**：容器测试需要Docker/Podman可用
3. **超时设置**：集成测试有默认超时，可以根据需要调整
4. **环境隔离**：每个测试使用临时目录，确保测试隔离