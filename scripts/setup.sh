#!/bin/bash

# QuantCode 快速安装脚本
# 用途：从零开始设置整个QuantCode环境
# 使用：curl -fsSL https://raw.githubusercontent.com/HKUST-QUANT-SOCIETY/quantcode/main/scripts/setup.sh | bash

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

echo "========================================="
echo "  QuantCode 快速安装向导"
echo "  HKUST QUANT SOCIETY Agent Group"
echo "========================================="
echo ""

# 1. 检查依赖
info "检查系统依赖..."

if ! command -v python3 &> /dev/null; then
    warn "Python 3未安装"
    echo "请访问: https://www.python.org/downloads/"
    exit 1
fi

if ! command -v git &> /dev/null; then
    warn "Git未安装"
    echo "macOS: brew install git"
    echo "Linux: sudo apt install git"
    exit 1
fi

if ! command -v bun &> /dev/null; then
    warn "Bun未安装，正在安装..."
    curl -fsSL https://bun.sh/install | bash
    export PATH="$HOME/.bun/bin:$PATH"
fi

# 2. Clone仓库
info "Clone QuantCode仓库..."
if [ ! -d "QUANTcode" ]; then
    git clone https://github.com/HKUST-QUANT-SOCIETY/quantcode.git QUANTcode
    cd QUANTcode
else
    cd QUANTcode
    git pull
fi

# 3. Clone OpenCode载体
info "Clone OpenCode桌面端..."
if [ ! -d "../opencode" ]; then
    cd ..
    git clone https://github.com/HKUST-QUANT-SOCIETY/opencode.git
    cd opencode
    bun install
    cd ../QUANTcode
else
    info "✓ OpenCode已存在"
fi

# 4. 安装Python包
info "安装QuantCode Python包..."
pip install -e .

# 5. 创建配置文件
info "创建配置文件..."
if [ ! -f "config.json" ]; then
    cp config.example.json config.json
    warn "⚠️ 请编辑 config.json 填入你的API keys"
fi

# 6. 完成
echo ""
echo "========================================="
info "✓ 安装完成！"
echo "========================================="
echo ""
echo "下一步："
echo "  1. 编辑 config.json，填入API keys"
echo "     - DeepSeek API: https://platform.deepseek.com"
echo "     - AutoEval API: 联系Agent组获取"
echo ""
echo "  2. 启动QuantCode:"
echo "     ./scripts/start-quantcode.sh"
echo ""
echo "  3. 查看用户手册:"
echo "     cat docs/USER_MANUAL.md"
echo ""
