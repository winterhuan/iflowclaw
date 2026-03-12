# iFlow Skills - 技能库

> 借鉴 GitHub 上最优秀的 AI Agent Skills 实践，精心打磨的技能集合

## 技能列表

### 🧠 产品与设计
| 技能 | 描述 | 触发场景 |
|------|------|----------|
| `@brainstorming` | 头脑风暴与创意规划 | 产品规划、功能设计、问题解决 |
| `@mvp-planner` | MVP 规划专家 | 启动新项目、验证产品想法 |

### 💻 开发与架构
| 技能 | 描述 | 触发场景 |
|------|------|----------|
| `@architecture` | 系统架构设计 | 设计新系统、技术选型、扩展规划 |
| `@tech-stack-advisor` | 技术栈选型顾问 | 技术选型、评估新技术 |
| `@api-design` | API 设计专家 | 设计新 API、API 版本升级 |
| `@database-design` | 数据库设计专家 | 设计 schema、性能优化 |

### 🔍 代码质量
| 技能 | 描述 | 触发场景 |
|------|------|----------|
| `@code-review` | 代码审查专家 | 代码审查、PR 审查、安全审查 |
| `@security-auditor` | 安全审计专家 | 安全审查、渗透测试、合规检查 |
| `@debugging` | 调试专家 | Bug 排查、性能诊断、故障排查 |
| `@testing-strategies` | 测试策略专家 | 建立测试体系、提高覆盖率 |

## 使用方式

在对话中直接引用技能：

```
用户：帮我设计一个电商系统的数据库

助手：我来使用 @database-design 技能帮你设计。
首先，让我们明确几个关键问题...
```

## 技能设计原则

### 1. 实用性优先
- 每个技能都解决具体场景
- 提供可操作的步骤和模板
- 包含真实案例和代码示例

### 2. 结构化输出
- 清晰的执行流程
- 标准化的输出格式
- 检查清单和最佳实践

### 3. 持续进化
- 基于 GitHub 高星标项目实践
- 参考 Anthropic、Vercel、Stripe 等团队经验
- 定期更新以反映最新最佳实践

## 参考来源

这些技能的设计参考了以下优秀的开源项目：

- **[VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)** - 官方团队技能集合
- **[sickn33/antigravity-awesome-skills](https://github.com/sickn33/antigravity-awesome-skills)** - 1272+ 技能的设计模式
- **[punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers)** - MCP 服务器分类组织
- **[promptslab/Awesome-Prompt-Engineering](https://github.com/promptslab/Awesome-Prompt-Engineering)** - Prompt 工程最佳实践
- **[anthropics/skills](https://github.com/anthropics/skills)** - Anthropic 官方技能
- **[vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills)** - Vercel 官方技能

## 贡献新技能

如果你想添加新技能：

1. 在 `.iflow/skills/` 目录创建 `{skill-name}.md`
2. 遵循现有技能格式：
   - 清晰的描述
   - 触发条件
   - 执行流程
   - 输出格式
   - 最佳实践
3. 在 README.md 中更新技能列表

## 技能模板

```markdown
# Skill: {Skill Name} - {简短描述}

## 描述
{详细描述这个技能解决什么问题}

## 触发条件
- {场景 1}
- {场景 2}

## 执行流程
### 1. {阶段 1}
{详细步骤}

### 2. {阶段 2}
{详细步骤}

## 输出格式
{标准化输出模板}

## 最佳实践
### DO
- ✅ {应该做的}

### DON'T
- ❌ {不应该做的}

## 相关技能
- @{skill-1} - {描述}
- @{skill-2} - {描述}
```
