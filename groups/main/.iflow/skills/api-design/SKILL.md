# Skill: API Design - API 设计专家

## 描述
设计清晰、一致、可扩展的 API。涵盖 RESTful、GraphQL、gRPC 等风格，提供设计原则、最佳实践和常见模式。

## 触发条件
- 设计新 API
- API 版本升级
- 解决 API 设计争议
- 文档化现有 API

## API 设计原则

### 1. 以消费者为中心
```
□ 使用领域术语，而非实现细节
□ 提供合理的默认值
□ 错误信息清晰可行动
□ 支持常见用例，不追求万能
```

### 2. 一致性
```
□ 命名约定统一
□ 错误格式一致
□ 分页方式一致
□ 认证方式一致
```

### 3. 可预测性
```
□ 相同输入产生相同输出
□ 幂等操作（安全重试）
□ 行为符合 HTTP 语义
□ 版本升级向后兼容
```

## RESTful API 设计

### URL 设计

#### 资源命名
```
✅ 正确：
GET    /users              # 获取用户列表
GET    /users/123          # 获取特定用户
POST   /users              # 创建用户
PUT    /users/123          # 全量更新用户
PATCH  /users/123          # 部分更新用户
DELETE /users/123          # 删除用户

❌ 错误：
GET    /getUsers           # 动词在 URL 中
GET    /user/getById       # 层级过深
POST   /users/createUser   # 冗余
```

#### 嵌套资源
```
✅ 正确：
GET /users/123/orders          # 获取用户的订单
GET /users/123/orders/456      # 获取用户的特定订单

POST /users/123/orders         # 为用户创建订单
（请求体中包含订单详情，而非 userId）
```

#### 过滤、排序、分页
```
# 过滤
GET /users?status=active&role=admin

# 排序
GET /users?sort=-created_at,name  # - 表示降序

# 分页（Cursor-based 推荐用于大数据集）
GET /users?cursor=abc123&limit=20

# 分页（Offset-based 适合小数据集）
GET /users?page=2&per_page=20
```

### HTTP 方法使用

| 方法 | 幂等性 | 用途 | 示例 |
|------|--------|------|------|
| GET | 是 | 获取资源 | GET /users/123 |
| POST | 否 | 创建资源 | POST /users |
| PUT | 是 | 全量更新 | PUT /users/123 |
| PATCH | 是 | 部分更新 | PATCH /users/123 |
| DELETE | 是 | 删除资源 | DELETE /users/123 |

### 状态码使用

#### 成功（2xx）
```
200 OK - 成功
201 Created - 创建成功
202 Accepted - 已接受，异步处理
204 No Content - 成功但无返回体
```

#### 客户端错误（4xx）
```
400 Bad Request - 请求格式错误
401 Unauthorized - 未认证
403 Forbidden - 无权限
404 Not Found - 资源不存在
409 Conflict - 资源冲突
422 Unprocessable Entity - 验证失败
429 Too Many Requests - 限流
```

#### 服务器错误（5xx）
```
500 Internal Server Error - 服务器内部错误
502 Bad Gateway - 网关错误
503 Service Unavailable - 服务不可用
504 Gateway Timeout - 网关超时
```

### 请求/响应格式

#### 请求体（POST/PUT/PATCH）
```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "role": "admin"
}
```

#### 成功响应
```json
{
  "data": {
    "id": "123",
    "name": "John Doe",
    "email": "john@example.com",
    "created_at": "2025-01-15T10:30:00Z"
  }
}
```

#### 列表响应
```json
{
  "data": [
    { "id": "1", "name": "User 1" },
    { "id": "2", "name": "User 2" }
  ],
  "pagination": {
    "total": 100,
    "per_page": 20,
    "current_page": 1,
    "total_pages": 5
  }
}
```

#### 错误响应
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数验证失败",
    "details": [
      {
        "field": "email",
        "message": "邮箱格式不正确"
      },
      {
        "field": "password",
        "message": "密码长度至少 8 位"
      }
    ]
  }
}
```

## GraphQL 设计

### Schema 设计原则
```graphql
# 使用名词，而非动词
type Query {
  user(id: ID!): User           # ✅
  getUser(id: ID!): User        # ❌ 避免动词前缀
}

# 使用 Input 类型处理复杂参数
input CreateUserInput {
  name: String!
  email: String!
}

type Mutation {
  createUser(input: CreateUserInput!): User!
}
```

### 分页（Relay 规范）
```graphql
type UserConnection {
  edges: [UserEdge!]!
  pageInfo: PageInfo!
}

type UserEdge {
  node: User!
  cursor: String!
}

type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}
```

## API 版本控制

### URL 路径版本（推荐）
```
/v1/users
/v2/users
```

### Header 版本
```
Accept: application/vnd.api+json;version=2
```

### 版本升级策略
```
1. 保持向后兼容
   - 添加新字段（不删除旧字段）
   - 添加新端点（不删除旧端点）
   - 废弃标记（Deprecation header）

2. 破坏性变更
   - 发布新版本
   - 维护旧版本至少 6-12 个月
   - 提前通知消费者
```

## 安全设计

### 认证
```
□ JWT（短有效期 + 刷新令牌）
□ OAuth 2.0 / OpenID Connect
□ API Keys（仅服务端使用）
□ mTLS（服务间通信）
```

### 授权
```
□ RBAC（角色基础访问控制）
□ ABAC（属性基础访问控制）
□ 资源级别权限检查
```

### 防护机制
```
□ 速率限制（Rate Limiting）
  X-RateLimit-Limit: 100
  X-RateLimit-Remaining: 99
  X-RateLimit-Reset: 1640995200

□ 请求大小限制
□ SQL 注入防护
□ XSS 防护
□ CSRF 防护
```

## API 文档

### OpenAPI 规范
```yaml
openapi: 3.0.0
info:
  title: Example API
  version: 1.0.0
paths:
  /users:
    get:
      summary: 获取用户列表
      parameters:
        - name: page
          in: query
          schema:
            type: integer
            default: 1
      responses:
        '200':
          description: 成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UserList'
```

### 文档工具
- **Swagger UI**：交互式文档
- **Postman**：API 测试和文档
- **Stoplight**：设计优先的文档
- **ReadMe**：开发者门户

## 性能优化

### 响应优化
```
□ 字段选择（sparse fieldsets）
  GET /users?fields=id,name,email

□ 数据压缩（gzip/brotli）
□ 缓存策略（ETag, Cache-Control）
□ 分页（避免大数据集）
```

### 批量操作
```
POST /batch
{
  "operations": [
    { "method": "GET", "path": "/users/1" },
    { "method": "GET", "path": "/users/2" }
  ]
}
```

## 相关技能
- @architecture - 系统架构设计
- @security-auditor - 安全审计
- @testing-strategies - 测试策略
