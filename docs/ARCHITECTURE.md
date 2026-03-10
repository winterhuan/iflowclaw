# iFlowClaw 架构

## 概述

iFlowClaw 使用显式代码导入和标准 Node.js 开发实践。

## 目录结构

```
src/
├── channels/
│   ├── feishu.ts         # 飞书渠道
│   ├── index.ts          # 渠道加载器
│   └── registry.ts       # 渠道注册 API
├── extensions/
│   ├── image-vision/     # 图片理解扩展
│   ├── index.ts          # 扩展注册
│   └── types.ts          # 扩展类型
└── ...                   # 核心模块
```

## 添加扩展

1. 在 `src/extensions/my-feature/` 创建扩展
2. 在 `src/extensions/index.ts` 注册

```typescript
export const myExtension: AgentInputExtension = {
  name: 'my-feature',
  version: '1.0.0',
  enhanceAgentInput: (context, draft) => {
    // 你的逻辑
  },
};
```

## 优势

- **显式**: 没有魔法代码变更
- **标准**: 常规 Node.js/TypeScript 开发
- **类型安全**: 完整的 TypeScript 支持
