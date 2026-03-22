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

# 检查 Python
if ! command -v python3 >/dev/null; then
    echo "❌ 需要安装 Python 3.11+"
    exit 1
fi

python3 - <<'PY'
import sys
major, minor = sys.version_info[:2]
if (major, minor) < (3, 11):
    raise SystemExit("❌ Python 版本需要 3.11+")
PY

echo "🚀 启动 iFlowClaw (开发模式)..."
cd "$PROJECT_ROOT"
python3 -m iflowclaw run
