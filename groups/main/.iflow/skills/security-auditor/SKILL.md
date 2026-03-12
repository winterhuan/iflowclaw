# Skill: Security Auditor - 安全审计专家

## 描述
进行全面的安全审计，识别潜在漏洞，提供修复建议。遵循 OWASP、NIST 等安全标准，覆盖 Web 应用、API、基础设施等各个层面。

## 触发条件
- 代码安全审查
- 渗透测试准备
- 安全合规检查
- 漏洞响应
- 安全培训

## 安全框架

### OWASP Top 10（2025）
1. **A01:2025** - 失效的访问控制
2. **A02:2025** - 加密机制失效
3. **A03:2025** - 注入攻击（SQL、NoSQL、命令注入）
4. **A04:2025** - 不安全设计
5. **A05:2025** - 安全配置错误
6. **A06:2025** - 易受攻击和过时的组件
7. **A07:2025** - 身份识别和认证失效
8. **A08:2025** - 软件和数据完整性故障
9. **A09:2025** - 安全日志和监控失效
10. **A10:2025** - 服务器端请求伪造（SSRF）

### 安全开发生命周期（SDL）
```
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│  培训   │ -> │  设计   │ -> │  实现   │ -> │  验证   │
└─────────┘    └─────────┘    └─────────┘    └─────────┘
                    │              │              │
                    ▼              ▼              ▼
               ┌─────────┐   ┌─────────┐   ┌─────────┐
               │威胁建模 │   │安全编码 │   │安全测试 │
               └─────────┘   └─────────┘   └─────────┘
```

## 审计维度

### 1. 认证与授权

#### 认证检查清单
```
□ 密码策略：
  - 最小长度（建议 12+）
  - 复杂度要求
  - 常见密码检查
  - 密码历史

□ 多因素认证（MFA）：
  - 敏感操作强制 MFA
  - TOTP/SMS/硬件密钥支持

□ 会话管理：
  - 安全的会话 ID 生成
  - 合理的过期时间
  - 登出时使会话失效
  - 并发会话控制

□ 密码重置：
  - 安全的令牌生成
  - 短有效期（15-30 分钟）
  - 一次性使用
  - 发送到注册邮箱
```

#### 授权检查清单
```
□ 访问控制：
  - 最小权限原则
  - 角色基础访问控制（RBAC）
  - 资源级别权限检查
  - 水平权限控制（防止访问他人数据）

□ JWT 安全：
  - 使用强签名算法（RS256/ES256）
  - 验证 issuer 和 audience
  - 设置合理的过期时间
  - 安全存储（HttpOnly cookie）
```

### 2. 输入验证与注入防护

#### SQL 注入防护
```
✅ 正确做法：
- 使用参数化查询
- 使用 ORM（如 Prisma、SQLAlchemy）
- 最小权限数据库用户

❌ 错误做法：
- 字符串拼接 SQL
- 用户输入直接放入查询

// 安全示例（Node.js/Prisma）
const user = await prisma.user.findUnique({
  where: { id: userId }  // 自动参数化
});

// 危险示例
const query = `SELECT * FROM users WHERE id = ${userId}`;
```

#### XSS 防护
```
□ 输出编码：
  - HTML 上下文：HTML 实体编码
  - JavaScript 上下文：JS 编码
  - URL 上下文：URL 编码

□ Content Security Policy (CSP)：
  ```
  Content-Security-Policy: 
    default-src 'self';
    script-src 'self' 'nonce-<random>';
    style-src 'self' 'unsafe-inline';
    img-src 'self' data: https:;
  ```

□ 其他措施：
  - HttpOnly Cookie
  - X-Frame-Options
  - X-Content-Type-Options
```

### 3. 敏感数据处理

#### 数据分类
```
🔴 高度敏感：
- 密码（必须哈希）
- 信用卡号（必须加密）
- 个人身份信息（PII）

🟡 中等敏感：
- 邮箱地址
- 电话号码
- 用户偏好

🟢 低敏感：
- 公开配置
- 非个人数据
```

#### 加密要求
```
密码存储：
- 算法：Argon2id、bcrypt、scrypt
- 禁止：MD5、SHA1、简单哈希

数据传输：
- 强制 HTTPS（TLS 1.3）
- HSTS 头部
- 证书固定（可选）

数据存储：
- 敏感字段加密（AES-256-GCM）
- 密钥管理（KMS、HSM）
```

### 4. API 安全

#### 认证机制
```
□ OAuth 2.0 / OpenID Connect
□ API Keys（仅用于服务端）
□ JWT（短有效期 + 刷新机制）
□ mTLS（服务间通信）
```

#### 防护措施
```
□ 速率限制：
  - 按 IP 限制
  - 按用户限制
  - 按 API key 限制

□ 请求验证：
  - 参数类型检查
  - 长度限制
  - 格式验证（JSON Schema）

□ 错误处理：
  - 不泄露敏感信息
  - 统一错误格式
  - 适当的日志记录
```

### 5. 基础设施安全

#### 容器安全
```
□ 使用最小基础镜像（Alpine、Distroless）
□ 以非 root 用户运行
□ 镜像扫描（Trivy、Snyk）
□ 不泄露敏感信息到镜像
□ 资源限制（CPU、内存）
```

#### 云安全
```
□ IAM 最小权限
□ 安全组/防火墙规则
□ 数据加密（静态 + 传输）
□ 日志审计（CloudTrail）
□ 定期安全扫描
```

## 审计输出格式

### 安全报告模板
```markdown
# 安全审计报告

## 执行摘要
- **风险等级**：🔴 高风险 / 🟡 中风险 / 🟢 低风险
- **发现漏洞**：X 个（严重：Y，高危：Z，中危：W，低危：V）
- **审计范围**：...
- **审计日期**：...

## 详细发现

### [HIGH] 漏洞标题
- **类别**：OWASP A03: 注入
- **位置**：文件路径:行号
- **描述**：...
- **影响**：...
- **复现步骤**：
  1. ...
  2. ...
- **修复建议**：...
- **参考**：OWASP Cheat Sheet

## 合规检查
- [ ] GDPR 要求
- [ ] SOC2 要求
- [ ] PCI DSS 要求（如适用）

## 修复优先级
1. 🔴 立即修复（严重/高危）
2. 🟡 本周修复（中危）
3. 🟢 下月修复（低危）

## 安全建议
- ...
```

## 工具推荐

### 静态分析（SAST）
- **Semgrep**：轻量级、规则丰富
- **SonarQube**：企业级、全面
- **CodeQL**：GitHub 集成、深度分析
- **Bandit**：Python 专用
- **ESLint Security**：JavaScript 专用

### 动态分析（DAST）
- **OWASP ZAP**：开源、功能全面
- **Burp Suite**：专业渗透测试
- **Nuclei**：快速扫描、模板丰富

### 依赖扫描
- **Snyk**：全面的漏洞数据库
- **Dependabot**：GitHub 原生集成
- **npm audit / pip-audit**：内置工具

### 秘密扫描
- **GitLeaks**：防止密钥泄露
- **TruffleHog**：深度扫描
- **GitHub Secret Scanning**：原生集成

## 安全编码实践

### 安全函数库
```python
# Python 示例
from bleach import clean
from cryptography.fernet import Fernet
import bcrypt

# 输入清理
user_input = clean(untrusted_html, tags=['p', 'br'])

# 密码哈希
hashed = bcrypt.hashpw(password, bcrypt.gensalt())

# 加密敏感数据
key = Fernet.generate_key()
cipher = Fernet(key)
encrypted = cipher.encrypt(sensitive_data)
```

```javascript
// Node.js 示例
import DOMPurify from 'isomorphic-dompurify';
import helmet from 'helmet';
import rateLimit from 'express-rate-limit';

// XSS 防护
const clean = DOMPurify.sanitize(dirtyHtml);

// 安全头部
app.use(helmet());

// 速率限制
const limiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 100
});
app.use(limiter);
```

## 相关技能
- @code-review - 代码审查
- @debugging - 调试专家
- @performance-optimizer - 性能优化
