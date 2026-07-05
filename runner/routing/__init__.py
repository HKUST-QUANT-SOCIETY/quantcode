"""Routing and guard modules — execution control layer for Agent orchestration.

Day 3 俞高磊：代码规则路由 + 死循环检测 + 迭代上限 + 状态指纹 + RLHF 记录。
Day 3+: AI 路由 (LLM trace analysis) + ML 门控分类器 + 组合路由。
"""

from .router import RouteDecision, RouteResult, route_next_step
from .guards import (
    GuardResult,
    WINDOW_SIZE,
    MAX_SAME_TOOL_IN_WINDOW,
    MAX_CONSECUTIVE_SAME_TOOL,
    MAX_FINGERPRINT_REPEAT,
    MAX_ITERATIONS,
    check_max_iterations,
    detect_loop,
    detect_loop_by_tool_frequency,
    detect_loop_by_fingerprint,
)
from .fingerprint import (
    FINGERPRINT_FIELDS,
    EXCLUDED_FIELDS,
    compute_state_fingerprint,
)
from .rlhf_logger import (
    REWARD,
    RLHF_PATH,
    log_rlhf_entry,
    make_rlhf_entry,
)
from .gate_classifier import (
    FEATURE_NAMES,
    GateClassifier,
    extract_features,
)
from .ai_router import (
    TraceAnalysis,
    ai_analyze_trace,
)
from .combined_router import (
    RouterMode,
    get_router,
    route,
)

__all__ = [
    # Router (rule)
    "RouteDecision",
    "RouteResult",
    "route_next_step",
    # Guards
    "GuardResult",
    "WINDOW_SIZE",
    "MAX_SAME_TOOL_IN_WINDOW",
    "MAX_CONSECUTIVE_SAME_TOOL",
    "MAX_FINGERPRINT_REPEAT",
    "MAX_ITERATIONS",
    "check_max_iterations",
    "detect_loop",
    "detect_loop_by_tool_frequency",
    "detect_loop_by_fingerprint",
    # Fingerprint
    "FINGERPRINT_FIELDS",
    "EXCLUDED_FIELDS",
    "compute_state_fingerprint",
    # RLHF logger
    "REWARD",
    "RLHF_PATH",
    "log_rlhf_entry",
    "make_rlhf_entry",
    # Gate classifier
    "FEATURE_NAMES",
    "GateClassifier",
    "extract_features",
    # AI router
    "TraceAnalysis",
    "ai_analyze_trace",
    # Combined router
    "RouterMode",
    "get_router",
    "route",
]
