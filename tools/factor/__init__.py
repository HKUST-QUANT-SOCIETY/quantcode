"""factor group tools — Day 4 尹一帆，Day 5 真版实现。

3 个 tool:
- match_main:因子想法 → 主线匹配结果（LLM 分析，失败时降级返回兼容结果）
- gen_schema:因子想法 + 匹配结果 → FactorSpec（LLM 生成，失败时降级 _fallback 标记）
- autoeval:FactorSpec → AutoEval 报告（真 API，未配置/失败时降级 _is_mock mock 数据，
  共享 flows.factor_autoeval.MOCK_AUTOEVAL_PAYLOAD_V1）
"""
