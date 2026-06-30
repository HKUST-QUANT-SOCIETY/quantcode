# tools/utils

跨组共享的小工具。

## 计划清单

| 文件 | 用途 | Owner | 状态 |
|---|---|---|---|
| `dedupe.py` | `@dedupe_within(seconds, key)` 装饰器 + SQLite 去重表 | 陈镇鸿 | Day 1 实现 |

## dedupe.py 路径契约（陈镇鸿 Day 1 实现前已冻结）

```python
from tools.utils.dedupe import dedupe_within

@dedupe_within(seconds=300, key=lambda commit_sha, msg: f"{commit_sha}:{hash(msg)}")
def github_pr_comment(commit_sha: str, msg: str):
    ...
```

- 实现约 30 行：装饰器 + SQLite 一张表（`dedupe_log(key, fn_name, first_call_at)`）
- 覆盖 tool：`github_pr_*` / `send_email` / `slack_notify` / `cross_team_notify`
- 不覆盖（天然幂等）：`autoeval_*` / `rag_*` / 文件覆盖写
- 单元测试在 `tests/test_dedupe.py`（陈镇鸿 Day 1 提交）
