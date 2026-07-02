"""
Memory GROUP隔离权限测试

Day 2上午任务（Lead）：验证groups scope的owner-only read/write权限隔离

QuantCode扩展MimoCode的3-scope（global/projects/sessions）到5-scope：
  global/projects/groups/sessions/tasks

关键新特性：groups scope enforces owner-only read/write
  - factor组写的memory，只有factor可读
  - risk组写的memory，只有risk可读
  - global scope的memory，所有组可读

参考：docs/QuantCode_Design.md §4.5
"""

import pytest
from pathlib import Path
from typing import Optional


# ============================================================================
# 预期的API接口（Memory FTS5实现后需满足这些接口）
# ============================================================================

class MemorySearchResult:
    """单条搜索结果"""
    def __init__(self, path: str, snippet: str, score: float,
                 scope: str, scope_id: str, type: str):
        self.path = path
        self.snippet = snippet
        self.score = score
        self.scope = scope
        self.scope_id = scope_id
        self.type = type


class MemoryService:
    """
    Memory FTS5服务接口

    尹一帆的实现需满足：
    1. search()支持scope/scope_id/type过滤
    2. search()自动enforce groups scope权限：
       - 传入group_owner参数（caller的group身份）
       - 如果scope='groups'且scope_id != group_owner，返回空（权限拒绝）
    3. write()写入时记录owner
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._mock_data: list[MemorySearchResult] = []

    def write(self, content: str, scope: str, scope_id: str,
              type: str, key: str) -> str:
        """
        写入memory

        Args:
            content: memory内容
            scope: global/projects/groups/sessions/tasks
            scope_id:
                - global scope: ""
                - projects scope: project_hash
                - groups scope: group name (e.g., "factor", "risk")
                - sessions scope: thread_id
                - tasks scope: task_uuid
            type: memory/checkpoint/progress/notes/...
            key: memory文件名（不含.md）

        Returns:
            写入的文件路径
        """
        # TODO: 尹一帆实现
        # 1. 构造路径：memory/{scope}/{scope_id}/{key}.md
        # 2. 写入文件
        # 3. reconcile()触发FTS5索引更新
        path = f"memory/{scope}/{scope_id}/{key}.md" if scope_id else f"memory/{scope}/{key}.md"

        # Mock: 添加到内存数据
        result = MemorySearchResult(
            path=path,
            snippet=content[:100],
            score=1.0,
            scope=scope,
            scope_id=scope_id,
            type=type
        )
        self._mock_data.append(result)
        return path

    def search(self, query: str, scope: Optional[str] = None,
               scope_id: Optional[str] = None, type: Optional[str] = None,
               group_owner: Optional[str] = None,
               limit: int = 10) -> list[MemorySearchResult]:
        """
        搜索memory（带权限检查）

        Args:
            query: FTS5查询字符串
            scope: 过滤scope
            scope_id: 过滤scope_id
            type: 过滤type
            group_owner: 调用者的group身份（用于groups scope权限检查）
                        例如："factor"表示factor组在调用
                        如果为None，不能访问任何groups scope的memory
            limit: 返回结果数

        Returns:
            搜索结果列表

        权限规则：
            - scope='global': 所有人可读
            - scope='groups' and scope_id==group_owner: 可读（owner访问自己的）
            - scope='groups' and scope_id!=group_owner: 拒绝（不能读别组的）
            - scope='groups' and group_owner is None: 拒绝（未认证）
        """
        # TODO: 尹一帆实现
        # 1. 构造FTS5 query（参考service.ts:70 buildFtsQuery）
        # 2. 构造WHERE条件（scope/scope_id/type）
        # 3. **权限检查**：
        #    - 如果查询scope='groups'且scope_id != group_owner，直接返回空
        #    - 如果未指定scope但结果中有groups scope的，过滤掉不属于group_owner的
        # 4. 执行SQL: SELECT ... FROM memory_fts_idx WHERE ...
        # 5. 应用score floor（参考service.ts:132）

        # Mock implementation
        results = self._mock_data

        # Filter by scope/scope_id/type
        if scope:
            results = [r for r in results if r.scope == scope]
        if scope_id:
            results = [r for r in results if r.scope_id == scope_id]
        if type:
            results = [r for r in results if r.type == type]

        # **权限检查：groups scope isolation**
        filtered = []
        for r in results:
            if r.scope == "groups":
                # groups scope需要权限检查
                if group_owner is None:
                    # 未认证，不能访问任何groups memory
                    continue
                if r.scope_id != group_owner:
                    # 不是自己的group，不能访问
                    continue
            # global/projects/sessions/tasks scope：暂不做权限检查（简化）
            filtered.append(r)

        # Filter by query (简化mock：substring match)
        if query:
            filtered = [r for r in filtered if query.lower() in r.snippet.lower()]

        return filtered[:limit]

    def reconcile(self) -> dict:
        """触发reconcile（磁盘 ↔ SQLite双向同步）"""
        # TODO: 尹一帆实现
        return {"indexed": 0, "pruned": 0}


# ============================================================================
# 测试用例
# ============================================================================

@pytest.fixture
def memory_service(tmp_path):
    """创建临时Memory服务"""
    db_path = tmp_path / "test_memory.db"
    service = MemoryService(str(db_path))
    return service


class TestGroupIsolation:
    """测试groups scope的权限隔离"""

    def test_factor_group_cannot_read_risk_memory(self, memory_service):
        """factor组不能读risk组的memory"""
        # risk组写入一条memory
        memory_service.write(
            content="风险因子：最大回撤计算逻辑",
            scope="groups",
            scope_id="risk",
            type="memory",
            key="max-drawdown-formula"
        )

        # factor组尝试读取risk的memory
        results = memory_service.search(
            query="回撤",
            scope="groups",
            scope_id="risk",
            group_owner="factor"  # factor组的身份
        )

        # 应该返回空（权限拒绝）
        assert len(results) == 0, "factor组不应该能读到risk组的memory"

    def test_risk_group_cannot_read_factor_memory(self, memory_service):
        """risk组不能读factor组的memory"""
        # factor组写入一条memory
        memory_service.write(
            content="PB-ROE因子：账面市值比 × 净资产收益率",
            scope="groups",
            scope_id="factor",
            type="memory",
            key="pb-roe-factor"
        )

        # risk组尝试读取factor的memory
        results = memory_service.search(
            query="PB-ROE",
            scope="groups",
            scope_id="factor",
            group_owner="risk"  # risk组的身份
        )

        # 应该返回空（权限拒绝）
        assert len(results) == 0, "risk组不应该能读到factor组的memory"

    def test_group_can_read_own_memory(self, memory_service):
        """组可以读自己的memory"""
        # factor组写入
        memory_service.write(
            content="PB-ROE因子：账面市值比 × 净资产收益率",
            scope="groups",
            scope_id="factor",
            type="memory",
            key="pb-roe-factor"
        )

        # factor组读取自己的memory
        results = memory_service.search(
            query="PB-ROE",
            scope="groups",
            scope_id="factor",
            group_owner="factor"  # factor组自己
        )

        # 应该能读到
        assert len(results) == 1
        assert results[0].scope_id == "factor"
        assert "PB-ROE" in results[0].snippet

    def test_unauthenticated_cannot_read_group_memory(self, memory_service):
        """未认证用户不能读任何group的memory"""
        # factor组写入
        memory_service.write(
            content="PB-ROE因子：账面市值比 × 净资产收益率",
            scope="groups",
            scope_id="factor",
            type="memory",
            key="pb-roe-factor"
        )

        # 未认证用户（group_owner=None）尝试读取
        results = memory_service.search(
            query="PB-ROE",
            scope="groups",
            scope_id="factor",
            group_owner=None  # 未认证
        )

        # 应该返回空
        assert len(results) == 0, "未认证用户不应该能读到group memory"

    def test_all_groups_can_read_global_memory(self, memory_service):
        """所有组都能读global scope的memory"""
        # 写入global memory
        memory_service.write(
            content="QuantCode架构设计：Pattern 1+2+5",
            scope="global",
            scope_id="",
            type="reference",
            key="architecture"
        )

        # factor组读取
        factor_results = memory_service.search(
            query="Pattern",
            scope="global",
            group_owner="factor"
        )

        # risk组读取
        risk_results = memory_service.search(
            query="Pattern",
            scope="global",
            group_owner="risk"
        )

        # 两个组都能读到
        assert len(factor_results) == 1
        assert len(risk_results) == 1
        assert "Pattern" in factor_results[0].snippet

    def test_cross_group_search_filters_results(self, memory_service):
        """跨组搜索时，自动过滤掉无权限的结果"""
        # factor组写入
        memory_service.write(
            content="PB-ROE因子：账面市值比 × 净资产收益率",
            scope="groups",
            scope_id="factor",
            type="memory",
            key="pb-roe-factor"
        )

        # risk组写入（也包含"因子"关键词）
        memory_service.write(
            content="风险因子：最大回撤计算逻辑",
            scope="groups",
            scope_id="risk",
            type="memory",
            key="risk-factor"
        )

        # factor组搜索"因子"（不指定scope_id，全局搜索）
        results = memory_service.search(
            query="因子",
            scope="groups",  # 只搜groups scope
            group_owner="factor"
        )

        # 应该只返回factor自己的结果
        assert len(results) == 1
        assert results[0].scope_id == "factor"
        assert "PB-ROE" in results[0].snippet


class TestMultiScopeAccess:
    """测试多scope的访问场景"""

    def test_mixed_scope_search(self, memory_service):
        """混合scope搜索（global + groups）"""
        # 写入global memory
        memory_service.write(
            content="因子设计原则：正交性、稳定性、可解释性",
            scope="global",
            scope_id="",
            type="reference",
            key="factor-design-principles"
        )

        # factor组写入
        memory_service.write(
            content="PB-ROE因子实现",
            scope="groups",
            scope_id="factor",
            type="memory",
            key="pb-roe"
        )

        # risk组写入
        memory_service.write(
            content="风险因子实现",
            scope="groups",
            scope_id="risk",
            type="memory",
            key="risk"
        )

        # factor组搜索"因子"（不限定scope）
        results = memory_service.search(
            query="因子",
            group_owner="factor"
        )

        # 应该返回：global的1条 + factor自己的1条 = 2条
        # 不应该返回risk的那条
        assert len(results) == 2
        scope_ids = {r.scope_id for r in results}
        assert "" in scope_ids  # global
        assert "factor" in scope_ids
        assert "risk" not in scope_ids


# ============================================================================
# 性能测试（可选）
# ============================================================================

class TestGroupIsolationPerformance:
    """验证权限检查不影响搜索性能"""

    @pytest.mark.skip(reason="等Memory FTS5实现后再测")
    def test_large_scale_group_search(self, memory_service):
        """大规模group memory搜索性能"""
        # 写入1000条不同group的memory
        for i in range(500):
            memory_service.write(
                content=f"factor memory {i}",
                scope="groups",
                scope_id="factor",
                type="memory",
                key=f"factor-{i}"
            )
            memory_service.write(
                content=f"risk memory {i}",
                scope="groups",
                scope_id="risk",
                type="memory",
                key=f"risk-{i}"
            )

        # factor组搜索（应该只返回自己的500条）
        import time
        start = time.time()
        results = memory_service.search(
            query="memory",
            scope="groups",
            group_owner="factor",
            limit=100
        )
        elapsed = time.time() - start

        assert len(results) == 100
        assert all(r.scope_id == "factor" for r in results)
        assert elapsed < 0.1, f"搜索耗时{elapsed:.3f}s，超过100ms阈值"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
