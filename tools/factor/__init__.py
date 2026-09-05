"""factor group tools — Day 4 尹一帆，Day 5 真版实现。

核心工具：
- match_main:因子想法 → 主线匹配结果（LLM 分析，失败时降级返回兼容结果）
- gen_schema:因子想法 + 匹配结果 → FactorSpec（LLM 生成，失败时降级 _fallback 标记）
- quant_evaluator: FactorSpec → canonical QuantEvaluator result envelope；不可用时
  返回 UNAVAILABLE，不生成 mock 指标
"""
