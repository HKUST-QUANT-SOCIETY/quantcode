"""Routing and guard modules — execution control layer for Agent orchestration.

Day 3 俞高磊：代码规则路由 + 死循环检测 + 迭代上限 + 状态指纹 + RLHF 记录。
Day 5: RLHF 格式重构 — 删 reward_key/REWARD，改为 system_decision + human_decision
         + gate_purpose + risk_score + label（4 路显式映射，非 XOR）。
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
    compute_state_fingerprint,
)
from .rlhf_logger import (
    RLHF_PATH,
    log_rlhf_entry,
    make_rlhf_entry,
)
from .session_review import (
    apply_judged_session,
    apply_session_verdict,
    reviewer_review_session,
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
    "compute_state_fingerprint",
    # RLHF logger
    "RLHF_PATH",
    "log_rlhf_entry",
    "make_rlhf_entry",
    # Session review (post-hoc label 回填 + judge 分支)
    "apply_judged_session",
    "apply_session_verdict",
    "reviewer_review_session",
]
