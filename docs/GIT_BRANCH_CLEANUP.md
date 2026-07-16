# Git 分支清理指南

> **目的**：梳理未合并的分支，明确每个分支的状态和处理方案
> **最后更新**：2026-07-15（Lead）

---

## 📊 当前分支状态分析

### ✅ 已合并到main的分支（可删除）

| 分支 | 最后提交 | 作者 | 状态 | 建议 |
|------|---------|------|------|------|
| `fix/risk-gate-unify` | c47d1dc | Lead | ✅ 已合并到main | **删除** |
| `lead/factor-prototype-migration` | d800873 | Lead | 🔶 部分内容在factor-demo-real-impl | **保留至合并后删除** |

**分析**：
- `fix/risk-gate-unify`: commit c47d1dc已经是main的HEAD，可以安全删除
- `lead/factor-prototype-migration`: 功能已被`lead/factor-demo-real-impl`超越

---

### 🔄 未合并但应该合并的分支

#### 1. `lead/factor-demo-real-impl` (当前分支)
**状态**: ✅ 已完成，等待合并

**内容**：
- match_main真LLM实现
- gen_schema真LLM实现
- autoeval真API实现
- TEST_GUIDE.md
- MODULE_ARCHITECTURE.md
- TESTING_MANUAL.md

**提交记录**：
```
0250494 docs: add module architecture and testing manual
b1c1c04 feat(factor): add autoeval real API implementation
0885537 feat(factor): add gen_schema real LLM + test guide
eccae30 feat(factor): add match_main real LLM implementation
```

**建议**: 
1. 创建PR合并到main
2. 合并后删除本地和远程分支

---

#### 2. `yifan-day5`
**状态**: 🔶 部分合并，有独立功能

**内容**：
- Dream后台调度器
- Distill原型（tool_call频率统计）
- RetryWrapper重试机制
- 6组ReAct端到端测试

**未合并的commits**（相对main）：
```
8dce3bc refactor(distill): 删除重复实现
bc3ad22 chore(gitignore): .superpowers/ 不入库
fcacae4 chore: 移出私人文档
...
```

**分析**：
- 大部分功能已经在main（通过其他分支合并）
- 有一些清理性commit（gitignore, docs）
- 需要尹一帆确认是否还有需要保留的内容

**建议**：
1. Review未合并的commits
2. 挑选有价值的cherry-pick到main
3. 或创建新PR合并剩余内容

---

#### 3. `feature/jerry-day5-demos`
**状态**: 🔶 Demo场景实现，待合并

**内容**：
- Strategy/Fundamental/Options demo收口
- Chroma PIT
- Human gate测试
- 填充报告

**未合并的commits**：
```
5d025a6 feat(day5): close Jerry §7 acceptance
764ae01 fix(fundamental): fill research markdown
b60d593 feat(day5): Jerry track demos
```

**建议**：
1. 创建PR合并到main
2. 这是Day 5的重要功能

---

#### 4. `agent/model-risk-gate-test-pr`
**状态**: 🔶 测试分支

**内容**：
- Model组risk-gate E2E测试
- ModelSpec fixture

**建议**：
1. 测试通过后合并到main
2. 或作为测试增强保留

---

#### 5. `zhenhong`
**状态**: 🤔 需要确认

**内容**：
- 已merge main
- 可能有额外工作

**建议**：
1. 与陈镇鸿确认是否还在使用
2. 如果不用了，删除

---

### 🗑️ 应该删除的远程分支

| 分支 | 原因 | 操作 |
|------|------|------|
| `origin/gaolei/day3-routing-guards` | Day 3旧分支 | 删除 |
| `origin/xinlinyang/day4-risk-after-agent-gate` | Day 4旧分支 | 删除 |
| `origin/xinlinyang/day4-risk-nonblocking` | Day 4旧分支 | 删除 |
| `origin/yifan-day4` | Day 4旧分支 | 删除 |
| `origin/yifan` | 旧分支 | 删除 |
| `origin/feature/jerry-day4-strategy-fundamental` | Day 4旧分支 | 删除 |
| `origin/gaolei/AI-router` | 旧实验分支 | 删除 |
| `origin/feature/jerry-day3-schema` | Day 3旧分支 | 删除 |
| `origin/xinlinyang/day3-risk-agent` | Day 3旧分支 | 删除 |

---

## 🔧 清理操作步骤

### 步骤1：合并重要分支

```bash
cd ~/Desktop/私募/QUANTcode

# 1. 创建PR合并 lead/factor-demo-real-impl
gh pr create --base main --head lead/factor-demo-real-impl \
  --title "feat(factor): Day 5 §6 factor收口 - 3工具真实实现" \
  --body "## 内容

- ✅ match_main真LLM实现
- ✅ gen_schema真LLM实现  
- ✅ autoeval真API实现
- ✅ TEST_GUIDE.md（6层测试）
- ✅ MODULE_ARCHITECTURE.md（15模块详解）
- ✅ TESTING_MANUAL.md（完整测试手册）

## 环境变量控制

\`QUANTCODE_FACTOR_USE_REAL_LLM=1\` 启用真实实现

## 测试

\`\`\`bash
python -m pytest tests/test_factor_*.py -v
\`\`\`
"

# 2. 合并 feature/jerry-day5-demos
gh pr create --base main --head feature/jerry-day5-demos \
  --title "feat(day5): Jerry §7 strategy/fundamental/options demo收口" \
  --body "Day 5 demo场景实现"

# 3. 合并 yifan-day5（如果确认需要）
# 先review未合并的commits
git log main..yifan-day5 --oneline
```

### 步骤2：删除已合并的本地分支

```bash
# 切换到main
git checkout main
git pull origin main

# 删除已合并的本地分支
git branch -d fix/risk-gate-unify
git branch -d lead/factor-prototype-migration  # 等factor-demo-real-impl合并后

# 删除旧的本地分支
git branch -D pr8-rebase
git branch -D pr11-rebase
git branch -D review/pr12
git branch -D fix/zhenhong-day4-review
git branch -D fix/yifan-day4-review
```

### 步骤3：删除远程旧分支

```bash
# Day 3旧分支
git push origin --delete gaolei/day3-routing-guards
git push origin --delete feature/jerry-day3-schema
git push origin --delete xinlinyang/day3-risk-agent

# Day 4旧分支
git push origin --delete xinlinyang/day4-risk-after-agent-gate
git push origin --delete xinlinyang/day4-risk-nonblocking
git push origin --delete yifan-day4
git push origin --delete feature/jerry-day4-strategy-fundamental

# 其他旧分支
git push origin --delete yifan
git push origin --delete gaolei/AI-router
```

### 步骤4：删除已合并的远程分支

```bash
# 等PR合并后
git push origin --delete fix/risk-gate-unify
git push origin --delete lead/factor-demo-real-impl  # PR合并后
git push origin --delete feature/jerry-day5-demos    # PR合并后
```

---

## 📋 团队确认事项

需要与团队成员确认以下分支：

### 尹一帆
- [ ] `yifan-day5`: 是否还有未合并的重要功能？
- [ ] 建议：review未合并commits，cherry-pick有价值的到main

### 陈镇鸿
- [ ] `zhenhong`: 是否还在使用？
- [ ] 建议：如不使用，删除

### 杨欣琳
- [ ] `xinlinyang/*`的Day 3/4分支都可以删除吗？
- [ ] 建议：确认后批量删除

### 俞高磊
- [ ] `gaolei/*`的旧分支都可以删除吗？
- [ ] 建议：确认后批量删除

### 刘炽
- [ ] `feature/jerry-day5-demos`: 创建PR合并
- [ ] `feature/jerry-day4-strategy-fundamental`: 删除

---

## 🎯 清理后的目标状态

清理完成后，应该只保留：

### 活跃分支
- `main` (主分支)
- `feat/quantcode-day5-ui` (opencode仓库)

### 临时分支（短期）
- 当前正在开发的feature分支
- 待review的PR分支

### 长期分支（如果有）
- `develop` (如果采用git-flow)
- `staging` (如果有staging环境)

---

## 📈 分支管理建议

### 命名规范

```
<type>/<scope>-<short-description>

type:
- feat: 新功能
- fix: 修复
- docs: 文档
- test: 测试
- refactor: 重构
- chore: 杂项

例如:
- feat/factor-llm-integration
- fix/risk-gate-threshold
- docs/testing-guide
```

### 生命周期

1. **创建**: 从main创建feature分支
2. **开发**: 在feature分支上提交
3. **PR**: 创建Pull Request
4. **Review**: 代码审查
5. **合并**: 合并到main
6. **删除**: 立即删除本地和远程分支

### 防止分支堆积

- PR合并后**立即删除**分支
- 每周清理stale分支
- 不再使用的分支标记为`archived/`前缀

---

## 🔍 查看分支状态的命令

```bash
# 查看所有分支（按日期排序）
git branch -a --sort=-committerdate

# 查看已合并到main的分支
git branch --merged main

# 查看未合并到main的分支
git branch --no-merged main

# 查看远程分支最后更新时间
git for-each-ref --sort=-committerdate refs/remotes/ \
  --format='%(committerdate:short) %(refname:short)'

# 查看分支的提交差异
git log main..branch-name --oneline

# 查看分支的commit数量
git rev-list --count main..branch-name
```

---

## 🚀 自动化清理脚本

创建清理脚本方便后续使用：

```bash
cat > ~/Desktop/私募/QUANTcode/scripts/cleanup-branches.sh << 'EOF'
#!/bin/bash
echo "🧹 清理Git分支..."

cd ~/Desktop/私募/QUANTcode

# 更新远程分支列表
git fetch --prune

# 列出已合并到main的本地分支
echo "📋 已合并到main的本地分支："
git branch --merged main | grep -v "^\*" | grep -v "main"

echo ""
read -p "删除这些本地分支？(y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git branch --merged main | grep -v "^\*" | grep -v "main" | xargs -n 1 git branch -d
    echo "✅ 本地分支已清理"
fi

# 列出stale远程分支（30天未更新）
echo ""
echo "📋 30天未更新的远程分支："
git for-each-ref --sort=-committerdate refs/remotes/ \
  --format='%(committerdate:short) %(refname:short)' | \
  awk -v date="$(date -v-30d +%Y-%m-%d)" '$1 < date {print $2}'

echo ""
echo "⚠️  远程分支需要手动确认后删除"
echo "命令: git push origin --delete <branch-name>"

EOF

chmod +x ~/Desktop/私募/QUANTcode/scripts/cleanup-branches.sh
```

---

## 📝 清理检查清单

- [ ] 确认所有Day 5功能分支已合并或有PR
- [ ] 删除Day 3/4的旧分支
- [ ] 删除已合并的feature分支
- [ ] 与团队成员确认个人分支状态
- [ ] 更新README标注活跃分支
- [ ] 设置GitHub分支保护规则（main分支）

---

**建议下一步**：
1. 立即为`lead/factor-demo-real-impl`创建PR
2. 与团队开会确认其他分支状态
3. 执行批量清理

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
