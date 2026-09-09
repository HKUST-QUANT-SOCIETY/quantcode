#!/bin/bash

# QuantCode 一键启动脚本
# 用途：检查依赖、配置、启动桌面端
# 作者：HKUST QUANT SOCIETY Agent Group
# 版本：v1.0

set -euo pipefail  # 遇到错误立即退出

# Resolve paths from the script location so the launcher works from any cwd.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
export QUANTCODE_ROOT="$PROJECT_ROOT"

python_bin="${QUANTCODE_PYTHON:-}"
if [ -z "$python_bin" ]; then
    for candidate in "$PROJECT_ROOT/.venv/bin/python" python3.12 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            python_bin="$candidate"
            break
        fi
    done
fi

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# 检查当前目录
if [ ! -f "$PROJECT_ROOT/README.md" ] || [ ! -d "$PROJECT_ROOT/quantcode" ]; then
    error "请在QuantCode项目根目录运行此脚本"
fi

info "QuantCode 一键启动脚本"
echo "================================"

# 1. 检查Python环境
info "检查Python环境..."
if [ -z "$python_bin" ]; then
    error "Python 3未安装。请先安装Python 3.12+"
fi

PYTHON_VERSION=$($python_bin --version | awk '{print $2}')
info "Python版本: $PYTHON_VERSION"

# 2. 检查Python包
info "检查QuantCode Python包..."
if ! PYTHONPATH="$PROJECT_ROOT" "$python_bin" -c "import runner" &> /dev/null; then
    warn "QuantCode包未安装，正在安装..."
    if command -v uv &> /dev/null; then
        uv sync --extra dev || error "安装失败"
        python_bin="$PROJECT_ROOT/.venv/bin/python"
    else
        "$python_bin" -m pip install -e ".[dev]" || error "安装失败"
    fi
    info "✓ Python包安装完成"
else
    info "✓ QuantCode包已安装"
fi

# 3. 检查可选运行配置
info "模型连接在 QuantCode 设置中填写 URL、API Key 和模型；无需另一份 Runner 密钥。"

# 4. 检查同仓桌面源码
info "检查 QuantCode 桌面工作区..."
OPENCODE_DIR="$PROJECT_ROOT/frontend"
if [ ! -f "$OPENCODE_DIR/package.json" ]; then
    error "缺少 frontend 工作区，请拉取完整的 quantcode 仓库"
fi

# 5. 检查Bun
info "检查Bun运行时..."
if ! command -v bun &> /dev/null; then
    error "Bun未安装。安装方法: curl -fsSL https://bun.sh/install | bash"
fi
info "✓ Bun已安装: $(bun --version)"

# 6. 安装锁定的桌面依赖
info "检查 QuantCode 桌面依赖..."
cd "$OPENCODE_DIR"
if [ ! -d "node_modules" ]; then
    warn "桌面依赖未安装，正在按锁文件安装..."
    bun install --frozen-lockfile || error "依赖安装失败"
    info "✓ QuantCode 桌面依赖安装完成"
else
    info "✓ QuantCode 桌面依赖已安装"
fi

# 7. 检查opencode.local.jsonc
info "检查桌面宿主配置..."
if [ ! -f "opencode.local.jsonc" ] && [ -f "opencode.jsonc" ]; then
    warn "opencode.local.jsonc不存在；使用仓库默认配置，不复制覆盖本地配置"
elif [ -f "opencode.local.jsonc" ]; then
    info "✓ opencode.local.jsonc已配置"
fi

if [ -z "${QUANTCODE_SSH_KEY_FINGERPRINT:-}" ] && [ ! -f "$PROJECT_ROOT/.opencode/authorized_groups.yaml" ]; then
    warn "未检测到 SSH roster 身份；MCP 将按 v5 规则保持 fail-closed。"
    warn "请由桌面 SSH Agent/Keychain bridge 注入 QUANTCODE_SSH_KEY_FINGERPRINT。"
fi

if [ "${1:-}" = "--check" ]; then
    cd "$PROJECT_ROOT"
    info "✓ QuantCode 启动前检查通过"
    exit 0
fi

# 8. 启动桌面端
echo "================================"
info "启动QuantCode桌面端..."
info "提示："
echo "  - 首次启动可能需要1-2分钟"
echo "  - 桌面端会在新窗口打开"
echo "  - 按Ctrl+C停止"
echo "  - 日志保存在: .quantcode/logs/"
echo ""
info "正在启动..."

# 启动并捕获错误
if bun run dev:desktop; then
    info "✓ 桌面端已启动"
else
    error "桌面端启动失败。请检查错误信息"
fi
