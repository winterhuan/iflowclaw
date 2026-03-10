#!/bin/bash
# 开发模式启动脚本 - 前台运行，适合开发调试
# 生产环境请使用: iflowclaw start 或 npm start

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 检查配置
if [ ! -f "$PROJECT_ROOT/.env" ] || ! grep -q "FEISHU_APP_ID=" "$PROJECT_ROOT/.env"; then
    echo "❌ 未配置，请先运行: npm run setup"
    exit 1
fi

# 检查依赖
if [ ! -d "$PROJECT_ROOT/node_modules" ]; then
    echo "📦 安装依赖..."
    cd "$PROJECT_ROOT" && npm install
fi

# 检查构建
if [ ! -d "$PROJECT_ROOT/dist" ] || [ "$(find "$PROJECT_ROOT/src" -newer "$PROJECT_ROOT/dist" -type f 2>/dev/null | wc -l)" -gt 0 ]; then
    echo "🔨 构建项目..."
    cd "$PROJECT_ROOT" && npm run build
fi

# 前台启动（开发模式）
echo "🚀 启动 iFlowClaw (开发模式)..."
cd "$PROJECT_ROOT"
node dist/index.js
