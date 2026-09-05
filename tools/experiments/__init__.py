"""AB 实验管理包 — FUNCTIONAL_SPEC P-05（ROADMAP A3 算法实验管理）。

- ab.py           : ABReport TypedDict schemas 层契约 + 报告装配/比较核
- _register.py    : run_ab_experiment / list_experiments / get_experiment 三工具注册
                    （import 即注册，_meta 通道，与 tools/algorithms/_register 同路）

与既有两套评估口径的关系：flows/factor_eval_real（proxy 收益口径的真实统计）
是本包的指标生产者；tools/algorithms 注册表（run_algorithm）是 challenger 可选
的算法路径。本包只做 A/B 编排、比较、归档（artifacts/experiments/）与排行榜。
"""