# Skill: Testing Strategies - 测试策略专家

## 描述
制定全面的测试策略，涵盖单元测试、集成测试、E2E 测试、性能测试等。帮助团队建立质量门禁，提高代码可靠性。

## 触发条件
- 建立测试体系
- 提高测试覆盖率
- 优化测试效率
- 选择测试工具
- 解决测试难题

## 测试金字塔

```
         /\
        /  \
       / E2E \          <-- 少量（用户旅程）
      /________\
     /          \
    / Integration \      <-- 中等（服务交互）
   /______________\
  /                \
 /     Unit          \   <-- 大量（业务逻辑）
/______________________\
```

**比例建议**：70% 单元测试 : 20% 集成测试 : 10% E2E 测试

## 测试类型详解

### 1. 单元测试（Unit Testing）

#### 目标
- 验证最小代码单元（函数、类、方法）
- 快速反馈（毫秒级）
- 高覆盖率（目标 80%+）

#### 原则（FIRST）
```
F - Fast：快速执行
I - Isolated：独立运行，无依赖
R - Repeatable：重复运行结果一致
S - Self-validating：自动验证结果
T - Timely：与代码同时编写（TDD）
```

#### 测试结构（AAA）
```typescript
// Arrange - 准备
test('should calculate total price with discount', () => {
  const cart = new Cart();
  cart.addItem({ price: 100, quantity: 2 });
  
  // Act - 执行
  const total = cart.calculateTotal({ discount: 0.1 });
  
  // Assert - 验证
  expect(total).toBe(180); // 200 * 0.9
});
```

#### 测试替身
```
Mock：完全模拟，验证交互
Stub：预设返回值
Spy：包装真实对象，记录调用
Fake：简化实现（如内存数据库）
```

### 2. 集成测试（Integration Testing）

#### 目标
- 验证组件间协作
- 测试数据库、API、消息队列交互
- 比单元测试慢，但比 E2E 快

#### 测试范围
```
□ 数据库集成：
  - 查询正确性
  - 事务处理
  - 迁移脚本

□ API 集成：
  - 请求/响应格式
  - 状态码
  - 错误处理

□ 外部服务：
  - 使用测试替身或沙盒环境
  - 契约测试（Pact）
```

#### 数据库测试示例
```typescript
// 使用测试数据库
import { setupTestDB, teardownTestDB } from './test-helpers';

describe('User Repository', () => {
  beforeAll(async () => {
    await setupTestDB();
  });
  
  afterAll(async () => {
    await teardownTestDB();
  });
  
  beforeEach(async () => {
    await db.truncate('users');
  });
  
  test('should create user', async () => {
    const user = await userRepo.create({
      email: 'test@example.com',
      name: 'Test User'
    });
    
    expect(user.id).toBeDefined();
    expect(user.email).toBe('test@example.com');
  });
});
```

### 3. E2E 测试（End-to-End）

#### 目标
- 模拟真实用户场景
- 验证完整业务流程
- 发现集成问题

#### 工具选择

| 工具 | 适用场景 | 特点 |
|------|----------|------|
| Playwright | 现代 Web 应用 | 多浏览器、自动等待、Trace |
| Cypress | 前端开发 | 实时重载、调试友好 |
| Selenium | 传统企业 | 生态成熟、支持广泛 |
| Puppeteer | Chrome 专用 | 无头浏览器、PDF 生成 |

#### Playwright 示例
```typescript
import { test, expect } from '@playwright/test';

test('user can complete purchase', async ({ page }) => {
  // 访问首页
  await page.goto('/');
  
  // 添加商品到购物车
  await page.click('[data-testid="product-1"]');
  await page.click('[data-testid="add-to-cart"]');
  
  // 结账流程
  await page.click('[data-testid="checkout"]');
  await page.fill('[name="email"]', 'user@example.com');
  await page.fill('[name="card"]', '4242424242424242');
  await page.click('[data-testid="submit-payment"]');
  
  // 验证订单成功
  await expect(page.locator('[data-testid="success"]')).toBeVisible();
  await expect(page.locator('[data-testid="order-number"]')).toHaveText(/ORD-\d+/);
});
```

#### 最佳实践
```
□ 使用 data-testid 而非 CSS 选择器
□ 每个测试独立，不依赖执行顺序
□ 使用 API 设置测试数据，而非 UI
□ 并行执行加速
□ 失败时截图/录像
```

### 4. 契约测试（Contract Testing）

#### 适用场景
- 微服务架构
- 前后端分离
- 第三方 API 集成

#### Pact 示例
```typescript
// 消费者测试（前端）
const provider = new Pact({
  consumer: 'Frontend',
  provider: 'UserService'
});

test('should get user details', async () => {
  await provider.addInteraction({
    state: 'user exists',
    uponReceiving: 'get user by id',
    withRequest: {
      method: 'GET',
      path: '/users/123'
    },
    willRespondWith: {
      status: 200,
      body: {
        id: 123,
        name: 'John Doe',
        email: 'john@example.com'
      }
    }
  });
  
  const user = await userService.getUser(123);
  expect(user.name).toBe('John Doe');
});
```

### 5. 性能测试

#### 类型
```
□ 负载测试：正常负载下的表现
□ 压力测试：极限负载下的稳定性
□ 峰值测试：突发流量处理
□ 耐力测试：长时间运行的稳定性
```

#### 工具
- **k6**：现代负载测试（代码即配置）
- **Artillery**：Node.js 原生
- **JMeter**：功能全面
- **Locust**：Python 编写，分布式

#### k6 示例
```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '2m', target: 100 },   //  ramp up
    { duration: '5m', target: 100 },   //  steady
    { duration: '2m', target: 200 },   //  ramp up
    { duration: '5m', target: 200 },   //  steady
    { duration: '2m', target: 0 },     //  ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<200'],   // 95% 请求 < 200ms
    http_req_failed: ['rate<0.01'],     // 错误率 < 1%
  },
};

export default function () {
  const res = http.get('https://api.example.com/users');
  check(res, {
    'status is 200': (r) => r.status === 200,
    'response time < 200ms': (r) => r.timings.duration < 200,
  });
  sleep(1);
}
```

### 6. 可视化测试

#### 工具
- **Storybook**：组件开发和测试
- **Chromatic**：自动化 UI 审查
- **Loki**：CI 中的视觉回归
- **Percy**：跨浏览器视觉测试

## 测试策略制定

### 质量门禁
```
┌─────────────────────────────────────────┐
│  提交前（Pre-commit）                    │
│  - Lint、Format                          │
│  - 相关单元测试                           │
│  - 耗时 < 30 秒                          │
├─────────────────────────────────────────┤
│  PR 检查（CI）                           │
│  - 全量单元测试（覆盖率检查）              │
│  - 集成测试                              │
│  - 安全扫描                              │
│  - 耗时 < 5 分钟                         │
├─────────────────────────────────────────┤
│  合并后（Post-merge）                     │
│  - E2E 测试                              │
│  - 性能基准测试                          │
│  - 部署到 staging                        │
│  - 耗时 < 30 分钟                        │
├─────────────────────────────────────────┤
│  发布前（Pre-release）                    │
│  - 全量 E2E 测试                         │
│  - 手动探索性测试                        │
│  - 安全审计                              │
└─────────────────────────────────────────┘
```

### 覆盖率目标
```
单元测试：
- 语句覆盖率：> 80%
- 分支覆盖率：> 70%
- 函数覆盖率：> 90%

集成测试：
- 关键路径：100%
- 错误处理：> 80%

E2E 测试：
- 核心用户旅程：100%
- 关键业务场景：100%
```

## 测试数据管理

### 策略
```
1. 工厂模式（Factory）：
   - 使用 faker 生成假数据
   - 支持覆盖特定字段

2. 快照测试：
   - 大型数据结构验证
   - 注意：敏感数据脱敏

3. 种子数据：
   - 测试环境专用数据集
   - 版本控制
```

### 工厂示例
```typescript
// factories/user.ts
import { faker } from '@faker-js/faker';

export const createUser = (overrides = {}) => ({
  id: faker.string.uuid(),
  email: faker.internet.email(),
  name: faker.person.fullName(),
  createdAt: faker.date.past(),
  ...overrides
});

// 使用
test('should display user', () => {
  const user = createUser({ name: 'Specific Name' });
  render(<UserCard user={user} />);
  expect(screen.getByText('Specific Name')).toBeInTheDocument();
});
```

## 常见反模式

### ❌ 避免
- 测试实现细节而非行为
- 测试之间共享状态
- 使用 sleep 等待异步操作
- 忽略测试失败
- 过度 mock（测试假的东西）

### ✅ 推荐
- 测试从用户视角出发
- 每个测试独立设置和清理
- 使用等待条件而非固定延迟
- 立即修复失败的测试
- 适度使用真实依赖

## 相关技能
- @code-review - 代码审查
- @debugging - 调试专家
- @performance-optimizer - 性能优化
