# Day 2 Memory FTS5实现指南

**协调人**：Lead  
**实现人**：尹一帆  
**时间**：Day 2上午（4h）

---

## 一、测试驱动的合约

权限测试已完成（7个测试全部通过）：
```bash
tests/test_memory_group_isolation.py  # 7 passed, 1 skipped
```

**你的实现必须让这些测试通过**（现在是mock实现，你要替换成真实FTS5）。

---

## 二、核心接口要求

### 2.1 MemoryService类

位置：`quantcode/memory/service.py`（需新建）

```python
class MemoryService:
    def __init__(self, db_path: str):
        """
        初始化Memory服务
        
        Args:
            db_path: SQLite数据库路径（包含FTS5索引）
        """
        pass

    def write(self, content: str, scope: str, scope_id: str,
              type: str, key: str) -> str:
        """
        写入memory文件并触发索引
        
        Returns:
            写入的文件路径
        """
        pass

    def search(self, query: str, scope: Optional[str] = None,
               scope_id: Optional[str] = None, type: Optional[str] = None,
               group_owner: Optional[str] = None,
               limit: int = 10) -> list[MemorySearchResult]:
        """
        搜索memory（带权限检查）
        
        **关键新增**：group_owner参数
        - 用于groups scope的权限检查
        - 如果scope='groups'且scope_id != group_owner，返回空
        """
        pass

    def reconcile(self) -> dict:
        """触发reconcile（磁盘 ↔ SQLite双向同步）"""
        pass
```

### 2.2 权限规则（QuantCode新增特性）

| Scope    | 权限规则                                      | 实现位置              |
|----------|-----------------------------------------------|----------------------|
| global   | 所有人可读                                    | search()无需检查     |
| projects | project成员可读写（Week 2实现）               | 暂不实现             |
| **groups** | **owner-only read/write（Day 2核心任务）** | **search()强制检查** |
| sessions | session owner可读写（Week 2实现）             | 暂不实现             |
| tasks    | task owner可读写（Week 2实现）                | 暂不实现             |

**Day 2只需实现groups scope的权限隔离**，其他scope暂时跳过权限检查。

---

## 三、实现步骤（参考MimoCode）

参考代码：`docs/mimocode-reference/memory/`（461行TS）

### 3.1 文件结构

```
quantcode/memory/
├── __init__.py
├── fts.py          # FTS5建表SQL（参考fts.sql.ts）
├── paths.py        # 路径解析（扩展到5-scope）
├── query.py        # FTS5查询构造（参考fts-query.ts）
├── service.py      # 主服务类（扩展权限检查）
└── reconcile.py    # reconcile机制（参考reconcile.ts）
```

### 3.2 FTS5建表（fts.py）

参考 `docs/mimocode-reference/memory/fts.sql.ts`：

```python
# quantcode/memory/fts.py
CREATE_MEMORY_FTS_TABLE = """
CREATE TABLE IF NOT EXISTS memory_fts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT UNIQUE NOT NULL,
  scope TEXT NOT NULL,        -- global/projects/groups/sessions/tasks
  scope_id TEXT NOT NULL,     -- ""/"<hash>"/"factor"/thread_id/task_uuid
  type TEXT NOT NULL,         -- memory/checkpoint/progress/notes/...
  body TEXT NOT NULL,
  fingerprint TEXT NOT NULL,  -- "{size}-{mtime}"用于变更检测
  last_indexed_at INTEGER NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts_idx 
USING fts5(
  body, 
  content='memory_fts', 
  content_rowid='id',
  tokenize='porter unicode61 remove_diacritics 2'  -- CJK支持
);

-- Triggers for auto-sync (参考fts.sql.ts:23-60)
CREATE TRIGGER IF NOT EXISTS memory_fts_ai AFTER INSERT ON memory_fts BEGIN
  INSERT INTO memory_fts_idx(rowid, body) VALUES (new.id, new.body);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_ad AFTER DELETE ON memory_fts BEGIN
  INSERT INTO memory_fts_idx(memory_fts_idx, rowid, body) VALUES('delete', old.id, old.body);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_au AFTER UPDATE ON memory_fts BEGIN
  INSERT INTO memory_fts_idx(memory_fts_idx, rowid, body) VALUES('delete', old.id, old.body);
  INSERT INTO memory_fts_idx(rowid, body) VALUES (new.id, new.body);
END;
"""
```

### 3.3 路径解析（paths.py）

扩展MimoCode的3-scope到5-scope：

```python
# quantcode/memory/paths.py
from typing import Literal, Optional
from dataclasses import dataclass

Scope = Literal["global", "projects", "groups", "sessions", "tasks"]
MemoryType = Literal["memory", "checkpoint", "progress", "notes", 
                     "feedback", "project", "reference", "user"]

@dataclass
class MemoryLocator:
    scope: Scope
    scope_id: str  # global→"", groups→"factor", sessions→thread_id, ...
    type: MemoryType
    key: str

def parse_path(abs_path: str) -> Optional[MemoryLocator]:
    """
    解析路径：memory/{scope}/{scope_id}/{key}.md
    
    Examples:
        memory/global/architecture.md
          → MemoryLocator(scope='global', scope_id='', type='memory', key='architecture')
        
        memory/groups/factor/pb-roe-factor.md
          → MemoryLocator(scope='groups', scope_id='factor', type='memory', key='pb-roe-factor')
        
        memory/sessions/abc123/checkpoint.md
          → MemoryLocator(scope='sessions', scope_id='abc123', type='checkpoint', key='checkpoint')
    """
    # 参考 docs/mimocode-reference/memory/paths.ts:45-52
    # 正则：/\/memory\/(global|projects|groups|sessions|tasks)(?:\/([^/]+))?\/(.+)\.md$/
    pass

def build_path(root: str, scope: Scope, scope_id: str, key: str) -> str:
    """
    构造路径（带安全检查，防止路径遍历）
    
    参考 paths.ts:105-112
    """
    pass
```

### 3.4 查询构造（query.py）

参考 `fts-query.ts`，将用户查询转换为FTS5 MATCH语法：

```python
# quantcode/memory/query.py
def build_fts_query(user_query: str) -> Optional[str]:
    """
    构造FTS5查询
    
    策略（参考fts-query.ts）：
    1. 分词：按标点/空格切分
    2. 每个token用双引号包裹（精确匹配）
    3. OR连接
    
    Examples:
        "PB-ROE因子" → '"PB" OR "ROE" OR "因子"'
        "最大回撤计算" → '"最大" OR "回撤" OR "计算"'
    
    Returns:
        FTS5 MATCH表达式，如果query为空则返回None
    """
    pass
```

### 3.5 Reconcile机制（reconcile.py）

参考 `reconcile.ts`：

```python
# quantcode/memory/reconcile.py
def reconcile_memory(root: str, db) -> dict:
    """
    双向同步：磁盘 ↔ SQLite
    
    流程（参考reconcile.ts:60-110）：
    1. 扫描磁盘：memory/{scope}/**/*.md
    2. 计算fingerprint："{size}-{mtime}"
    3. 对比DB中的fingerprint：
       - 不同 → 重新索引（UPDATE memory_fts）
       - 磁盘有DB没有 → 插入（INSERT）
       - DB有磁盘没有 → 删除（DELETE，自动触发FTS5清理）
    
    Returns:
        {"indexed": int, "pruned": int}
    """
    pass
```

### 3.6 主服务（service.py）★核心

```python
# quantcode/memory/service.py
import sqlite3
from typing import Optional
from .fts import CREATE_MEMORY_FTS_TABLE
from .query import build_fts_query
from .reconcile import reconcile_memory

class MemoryService:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db = sqlite3.connect(db_path)
        self.db.executescript(CREATE_MEMORY_FTS_TABLE)
    
    def search(self, query: str, scope: Optional[str] = None,
               scope_id: Optional[str] = None, type: Optional[str] = None,
               group_owner: Optional[str] = None,
               limit: int = 10) -> list:
        """
        参考 service.ts:52-134
        
        **QuantCode新增逻辑**（service.ts没有，需要你加）：
        
        # 1. 权限预检查（groups scope）
        if scope == "groups":
            if group_owner is None:
                return []  # 未认证，拒绝
            if scope_id and scope_id != group_owner:
                return []  # 访问别组的，拒绝
        
        # 2. 构造FTS5查询
        fts_query = build_fts_query(query)
        if not fts_query:
            return []
        
        # 3. 构造WHERE条件
        conditions = []
        params = []
        if scope:
            conditions.append("memory_fts.scope = ?")
            params.append(scope)
        if scope_id:
            conditions.append("memory_fts.scope_id = ?")
            params.append(scope_id)
        if type:
            conditions.append("memory_fts.type = ?")
            params.append(type)
        where_clause = f"AND {' AND '.join(conditions)}" if conditions else ""
        
        # 4. 执行查询
        sql = f'''
            SELECT memory_fts.path, memory_fts.scope, memory_fts.scope_id, 
                   memory_fts.type,
                   snippet(memory_fts_idx, 0, '<<', '>>', '...', 32) AS snippet,
                   bm25(memory_fts_idx) AS score
            FROM memory_fts_idx
            JOIN memory_fts ON memory_fts.id = memory_fts_idx.rowid
            WHERE memory_fts_idx MATCH ?
            {where_clause}
            ORDER BY score
            LIMIT ?
        '''
        
        fetch_limit = min(limit * 3, 50)  # over-fetch for score filtering
        rows = self.db.execute(sql, [fts_query, *params, fetch_limit]).fetchall()
        
        # 5. 权限后过滤（如果未指定scope，结果可能包含多个scope）
        results = []
        for row in rows:
            path, scope_val, scope_id_val, type_val, snippet, score = row
            
            # groups scope的结果需要二次检查
            if scope_val == "groups":
                if group_owner is None or scope_id_val != group_owner:
                    continue  # 过滤掉无权限的
            
            results.append({
                "path": path,
                "scope": scope_val,
                "scope_id": scope_id_val,
                "type": type_val,
                "snippet": snippet,
                "score": -score  # BM25返回负数，转正
            })
        
        # 6. Score floor过滤（参考service.ts:132）
        if not results:
            return []
        
        top_score = results[0]["score"]
        floor_ratio = 0.15
        cutoff = top_score * floor_ratio if floor_ratio > 0 else float('-inf')
        
        return [r for i, r in enumerate(results) 
                if i == 0 or r["score"] >= cutoff][:limit]
    
    def write(self, content: str, scope: str, scope_id: str,
              type: str, key: str) -> str:
        """写入memory文件 + 触发reconcile"""
        from .paths import build_path
        import os
        from datetime import datetime
        
        # 1. 构造路径
        root = "memory"  # TODO: 从config读取
        path = build_path(root, scope, scope_id, key)
        
        # 2. 写入文件
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        
        # 3. 触发reconcile（更新索引）
        self.reconcile()
        
        return path
    
    def reconcile(self) -> dict:
        """触发reconcile"""
        root = "memory"  # TODO: 从config读取
        return reconcile_memory(root, self.db)
```

---

## 四、验收标准

### 4.1 测试通过

```bash
python -m pytest tests/test_memory_group_isolation.py -v
# 必须：7 passed
```

### 4.2 手工验证

```python
# 在Python REPL中
from quantcode.memory.service import MemoryService

service = MemoryService("test.db")

# factor组写入
service.write(
    content="PB-ROE因子实现",
    scope="groups",
    scope_id="factor",
    type="memory",
    key="pb-roe"
)

# factor组可以读到
results = service.search("PB-ROE", scope="groups", scope_id="factor", group_owner="factor")
assert len(results) == 1

# risk组读不到
results = service.search("PB-ROE", scope="groups", scope_id="factor", group_owner="risk")
assert len(results) == 0  # ✅ 权限隔离生效
```

### 4.3 性能要求

- 1000条memory的搜索延迟 < 100ms
- CJK分词正确（"PB-ROE因子"能匹配"因子"单字搜索）

---

## 五、协调点

### 5.1 你遇到问题时找我（Lead）

- [ ] FTS5建表SQL报错
- [ ] 权限检查逻辑不清楚
- [ ] reconcile同步策略疑问
- [ ] 测试无法通过

### 5.2 我（Lead）下午会测试

- [ ] checkpoint恢复流程（依赖你的Memory实现）
- [ ] 跨组协调（确保factor和risk的memory真的隔离）

### 5.3 晚上Standup我会检查

- [ ] `quantcode/memory/`目录是否建立
- [ ] 7个测试是否全部通过
- [ ] 是否有blocker需要解决

---

## 六、参考资料

| 文档                                      | 重点                          |
|-------------------------------------------|-------------------------------|
| docs/QuantCode_Design.md §4.5            | Memory系统架构 + SQL schema   |
| docs/mimocode-reference/memory/          | 461行TS参考实现               |
| tests/test_memory_group_isolation.py     | TDD合约（你的目标）           |
| docs/Day2_TaskList.md §1.2               | 任务清单                      |

---

## 七、时间规划（4h）

| 时间段  | 任务                              | 产出                     |
|---------|-----------------------------------|--------------------------|
| 0-1h    | 搭建框架（5个文件 + __init__.py） | `quantcode/memory/`建立  |
| 1-2h    | FTS5 + paths + query实现          | 基础功能可用             |
| 2-3h    | service.py实现 + 权限检查         | 测试开始通过             |
| 3-4h    | reconcile + 调试 + 测试收尾       | 7 passed ✅              |

---

开始吧！有问题随时叫我。

-- Lead
