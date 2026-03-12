# Skill: Database Design - 数据库设计专家

## 描述
设计高效、可扩展的数据库 schema。涵盖关系型数据库和 NoSQL 数据库的设计原则、范式、反范式、索引策略等。

## 触发条件
- 设计新数据库 schema
- 数据库性能优化
- 数据迁移规划
- 选择数据库类型

## 设计原则

### 1. 理解访问模式
```
在动手设计前，先回答：
□ 读多写少还是读写均衡？
□ 查询模式是什么？（点查、范围查、聚合）
□ 数据增长预期？
□ 一致性要求？（强一致还是最终一致）
□ 多租户还是单租户？
```

### 2. 选择合适的数据库

| 场景 | 推荐 | 原因 |
|------|------|------|
| 事务型业务 | PostgreSQL | ACID、复杂查询、JSON 支持 |
| 高并发读写 | MySQL | 成熟、生态丰富 |
| 灵活 schema | MongoDB | 快速迭代、文档模型 |
| 缓存/会话 | Redis | 内存存储、超高性能 |
| 全文搜索 | Elasticsearch | 倒排索引、分词 |
| 时序数据 | TimescaleDB | 时间序列优化 |
| 图数据 | Neo4j | 关系遍历优化 |
| 大数据量 | Cassandra | 线性扩展 |

## 关系型数据库设计

### 范式与反范式

#### 第三范式（3NF）
```sql
-- ✅ 符合 3NF
users
- id (PK)
- name
- email
- created_at

orders
- id (PK)
- user_id (FK)
- total_amount
- status
- created_at

order_items
- id (PK)
- order_id (FK)
- product_id (FK)
- quantity
- price
```

#### 反范式（为了性能）
```sql
-- 在订单中冗余用户名称（避免 JOIN）
orders
- id (PK)
- user_id (FK)
- user_name  -- 反范式字段
- total_amount
- status

-- 触发器或应用层保持同步
```

### 字段设计

#### 数据类型选择
```sql
-- 优先使用更精确的类型
VARCHAR(n)    -- 变长字符串
TEXT          -- 长文本
INTEGER       -- 整数（4字节）
BIGINT        -- 大整数（8字节）
NUMERIC(p,s)  -- 精确小数（金额）
TIMESTAMPTZ   -- 带时区的时间戳
UUID          -- 全局唯一标识
JSONB         -- JSON 数据（PostgreSQL）
ENUM          -- 枚举值
```

#### 金额计算
```sql
-- ✅ 正确：使用整数（分）或 NUMERIC
amount_cents BIGINT  -- 存储 100 表示 $1.00
-- 或
amount NUMERIC(19,4) -- 精确小数

-- ❌ 错误：使用 FLOAT/DOUBLE
amount FLOAT  -- 精度丢失！
```

### 索引设计

#### 索引类型
```sql
-- B-tree（默认，适合等值和范围查询）
CREATE INDEX idx_users_email ON users(email);

-- 复合索引（最左前缀原则）
CREATE INDEX idx_orders_user_created 
ON orders(user_id, created_at DESC);

-- 唯一索引
CREATE UNIQUE INDEX idx_users_email_unique ON users(email);

-- 部分索引（只索引满足条件的行）
CREATE INDEX idx_orders_pending 
ON orders(created_at) 
WHERE status = 'pending';

-- 表达式索引
CREATE INDEX idx_users_lower_email 
ON users(LOWER(email));

-- GIN 索引（PostgreSQL，适合 JSON 和数组）
CREATE INDEX idx_products_tags ON products USING GIN(tags);
```

#### 索引原则
```
✅ 应该索引：
- WHERE 条件中的列
- JOIN 条件的列
- ORDER BY 的列
- 外键列（自动创建）

❌ 避免索引：
- 低基数列（如性别、布尔值）
- 频繁更新的列
- 小表（全表扫描更快）
```

### 主键选择

#### 自增 ID vs UUID
```sql
-- 自增 ID（SERIAL/BIGSERIAL）
优点：
- 占用空间小（8字节）
- 插入性能高（顺序写入）
- 可读性好

缺点：
- 容易预测（安全风险）
- 分片困难
- 合并数据冲突

-- UUID
优点：
- 全局唯一
- 安全（不可预测）
- 分片友好

缺点：
- 占用空间大（16字节）
- 插入性能低（随机写入）
- 可读性差

-- 折中：ULID（时间排序的 UUID）
```

### 分表分库策略

#### 垂直分表
```
users
├── users_basic (id, username, email)  -- 高频访问
└── users_profile (id, bio, avatar)     -- 低频访问
```

#### 水平分表（Sharding）
```sql
-- 按用户 ID 取模分表
users_0: id % 4 = 0
users_1: id % 4 = 1
users_2: id % 4 = 2
users_3: id % 4 = 3

-- 或按时间分表（日志、订单）
orders_2024_01
orders_2024_02
orders_2024_03
```

## NoSQL 设计

### MongoDB 文档设计

#### 嵌入 vs 引用
```javascript
// ✅ 嵌入（一对少，一起访问）
{
  _id: ObjectId("..."),
  name: "John",
  addresses: [
    { street: "123 Main St", city: "NYC" },
    { street: "456 Oak Ave", city: "LA" }
  ]
}

// ✅ 引用（一对多，独立访问）
// users collection
{ _id: userId, name: "John" }

// posts collection
{ 
  _id: postId, 
  user_id: userId,  // 引用
  title: "..." 
}
```

#### 设计模式
```javascript
// 桶模式（时间序列数据）
{
  sensor_id: "A123",
  date: ISODate("2024-01-15"),
  measurements: [
    { time: "00:00", temp: 20 },
    { time: "00:01", temp: 21 },
    // ... 每小时一个文档，而非每分钟
  ]
}

// 子集模式（大文档拆分）
// 频繁访问的部分
{ _id: 1, name: "Product", price: 100 }

// 不常访问的部分
{ _id: 1, description: "...", reviews: [...] }
```

### Redis 设计

#### 数据结构选择
```
String：缓存、计数器、分布式锁
Hash：对象存储、购物车
List：队列、时间线
Set：标签、共同关注
Sorted Set：排行榜、延迟队列
Bitmap：签到、在线状态
HyperLogLog：UV 统计
Stream：消息队列
```

#### 键命名规范
```
格式：资源类型:标识:属性

user:1000:profile
user:1000:settings
product:500:inventory
session:abc123:data
cache:api:users:list
```

## 性能优化

### 查询优化
```sql
-- ✅ 使用 EXPLAIN ANALYZE 分析查询
EXPLAIN ANALYZE 
SELECT * FROM orders 
WHERE user_id = 123 
AND created_at > '2024-01-01';

-- 关注：
-- - Seq Scan（全表扫描）-> 需要索引
-- - Nested Loop（嵌套循环）-> 小数据集 OK，大数据集考虑 Hash Join
```

### 连接池配置
```
最小连接数：5-10
最大连接数：根据 CPU 核心数和并发量
连接超时：30秒
空闲超时：10分钟
```

### 缓存策略
```
Cache-Aside（旁路缓存）：
1. 先查缓存
2. 缓存未命中查数据库
3. 写入缓存

Read-Through：
- 缓存未命中时自动加载

Write-Through：
- 写缓存同时写数据库

Write-Behind：
- 先写缓存，异步写数据库
```

## 迁移策略

### 零停机迁移
```
1. 双写阶段
   - 应用同时写入新旧 schema
   - 读取仍从旧 schema

2. 回填阶段
   - 批量迁移历史数据
   - 验证数据一致性

3. 切换阶段
   - 读取切换到新 schema
   - 观察一段时间

4. 清理阶段
   - 停止写入旧 schema
   - 删除旧表
```

### 版本控制
```sql
-- 使用迁移工具（Flyway、Liquibase）
V1__create_users_table.sql
V2__add_user_profile.sql
V3__create_orders_table.sql
```

## 监控指标

```
□ 查询性能：
  - 慢查询数量
  - 平均查询时间
  - P95/P99 延迟

□ 连接数：
  - 活跃连接
  - 空闲连接
  - 等待队列

□ 资源使用：
  - CPU 使用率
  - 内存使用
  - 磁盘 I/O
  - 磁盘空间

□ 复制延迟（主从）：
  - 秒级延迟
```

## 相关技能
- @architecture - 系统架构设计
- @performance-optimizer - 性能优化
- @tech-stack-advisor - 技术栈选型
