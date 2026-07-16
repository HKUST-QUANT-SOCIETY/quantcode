#!/bin/bash

# QuantCode 一键启动脚本
# 用途：检查依赖、配置、启动桌面端
# 作者：HKUST QUANT SOCIETY Agent Group
# 版本：v1.0

set -e  # 遇到错误立即退出

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
if [ ! -f "README.md" ] || [ ! -d "quantcode" ]; then
    error "请在QuantCode项目根目录运行此脚本"
fi

info "QuantCode 一键启动脚本"
echo "================================"

# 1. 检查Python环境
info "检查Python环境..."
if ! command -v python3 &> /dev/null; then
    error "Python 3未安装。请先安装Python 3.12+"
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
info "Python版本: $PYTHON_VERSION"

# 2. 检查Python包
info "检查QuantCode Python包..."
if ! python3 -c "import runner" &> /dev/null; then
    warn "QuantCode包未安装，正在安装..."
    pip install -e . || error "安装失败"
    info "✓ Python包安装完成"
else
    info "✓ QuantCode包已安装"
fi

# 3. 检查配置文件
info "检查配置文件..."
if [ ! -f "config.json" ]; then
    warn "config.json不存在，从示例文件创建..."
    if [ -f "config.example.json" ]; then
        cp config.example.json config.json
        warn "⚠️ 请编辑config.json填入真实的API keys"
        warn "   DeepSeek API: https://platform.deepseek.com"
        warn "   编辑完成后重新运行此脚本"
        exit 1
    else
        error "config.example.json不存在"
    fi
else
    # 检查API key是否配置
    if grep -q "your-.*-api-key-here" config.json; then
        error "config.json中仍有示例API key，请先配置真实的keys"
    fi
    info "✓ config.json已配置"
fi

# 4. 检查OpenCode桌面端
info "检查OpenCode桌面端..."
if [ ! -d "../opencode" ] && [ ! -d "opencode" ]; then
    error "OpenCode桌面端未找到。请先clone: gh repo clone HKUST-QUANT-SOCIETY/opencode"
fi

# 确定opencode路径
if [ -d "../opencode" ]; then
    OPENCODE_DIR="../opencode"
elif [ -d "opencode" ]; then
    OPENCODE_DIR="opencode"
fi

# 5. 检查Bun
info "检查Bun运行时..."
if ! command -v bun &> /dev/null; then
    error "Bun未安装。安装方法: curl -fsSL https://bun.sh/install | bash"
fi
info "✓ Bun已安装: $(bun --version)"

# 6. 安装OpenCode依赖
info "检查OpenCode依赖..."
cd "$OPENCODE_DIR"
if [ ! -d "node_modules" ]; then
    warn "OpenCode依赖未安装，正在安装..."
    bun install || error "依赖安装失败"
    info "✓ OpenCode依赖安装完成"
else
    info "✓ OpenCode依赖已安装"
fi

# 7. 检查opencode.local.jsonc
info "检查OpenCode配置..."
if [ ! -f "opencode.local.jsonc" ]; then
    if [ -f "opencode.jsonc" ]; then
        warn "opencode.local.jsonc不存在，从opencode.jsonc复制..."
        cp opencode.jsonc opencode.local.jsonc
        info "✓ 已创建opencode.local.jsonc"
    else
        error "opencode.jsonc不存在"
    fi
else
    info "✓ opencode.local.jsonc已配置"
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
