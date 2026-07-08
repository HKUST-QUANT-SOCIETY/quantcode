"""factor group tools — Day 4 尹一帆。

3 个 stub tool:
- match_main:因子想法 → 主线匹配结果
- gen_schema:因子想法 + 匹配结果 → FactorSpec
- autoeval:FactorSpec → AutoEval 报告(共享 flows.factor_autoeval.MOCK_AUTOEVAL_PAYLOAD_V1)

后续接真 LLM(Lead / 陈镇鸿 Day 4 §6)时,只替换各 stub 的 _execute 函数体,
schema / registry / AgentRunner 全不动。
"""
