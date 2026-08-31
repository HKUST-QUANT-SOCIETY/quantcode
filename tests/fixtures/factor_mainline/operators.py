"""Mock 主线因子库 — 算子白名单 fixture。"""

OPERATORS = {
    "ts_mean": {
        "name": "ts_mean",
        "description": "时序窗口均值",
        "params": ["window"],
        "example": "ts_mean(close, 20)",
    },
    "ts_std": {
        "name": "ts_std",
        "description": "时序窗口标准差",
        "params": ["window"],
        "example": "ts_std(volume, 60)",
    },
    "fundamental_ratio": {
        "name": "fundamental_ratio",
        "description": "基本面比值(PB/PE/PS/ROE等)",
        "params": ["numerator", "denominator"],
        "example": "fundamental_ratio('market_cap', 'book_value')",
    },
    "cross_sectional_rank": {
        "name": "cross_sectional_rank",
        "description": "截面排序归一化",
        "params": ["universe"],
        "example": "cross_sectional_rank(factor_value)",
    },
}

COMPATIBILITY_RULES = {
    "PB": {"operators": ["fundamental_ratio"], "numerator": "market_cap", "denominator": "book_value"},
    "momentum": {"operators": ["ts_mean", "cross_sectional_rank"], "window": 20},
}
