"""
Execution guards — loop detection + max-iteration limit.

Five layers of loop detection:
  1. Max-iteration hard cap
  2. Tool-call frequency (sliding window + consecutive)
  3. Repeated state fingerprint (Agent making no progress)
  4. Consecutive errors (result-driven, regardless of tool name)
  5. TF-IDF embedding (multi-cycle semantic stagnation)

Plus a hard iteration cap.  Used by router.py to decide whether to abort.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# from .fingerprint import compute_state_fingerprint

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

WINDOW_SIZE = 10               # sliding window for tool-call history
MAX_SAME_TOOL_IN_WINDOW = 8    # same tool ≤7 times in the window (>=8 triggers abort)
MAX_CONSECUTIVE_SAME_TOOL = 5  # same tool ≤4 consecutive calls
MAX_FINGERPRINT_REPEAT = 3     # same fingerprint ≤2 repeats before abort
MAX_ITERATIONS = 100           # hard iteration cap

# TF-IDF embedding stopper
EMBED_WINDOW_SIZE = 6          # sliding window steps for TF-IDF comparison
EMBED_PATIENCE = 3             # consecutive similar windows before trigger
EMBED_SIMILARITY_THRESHOLD = 0.85

# Consecutive error stopper
MAX_CONSECUTIVE_ERRORS = 5     # consecutive failed steps before trigger


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class GuardResult:
    """Unified guard check outcome."""
    aborted: bool = False
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Layer 1: Max iterations
# ---------------------------------------------------------------------------

def check_max_iterations(
    iteration_count: int,
    max_iterations: int = MAX_ITERATIONS,
) -> GuardResult:
    """Return an abort result if `iteration_count` exceeds the cap."""
    if iteration_count > max_iterations:
        return GuardResult(
            aborted=True,
            reason="max_iterations_exceeded",
            detail={
                "iteration_count": iteration_count,
                "max_iterations": max_iterations,
            },
        )
    return GuardResult()


# ---------------------------------------------------------------------------
# Layer 2: Tool-call frequency
# ---------------------------------------------------------------------------

def detect_loop_by_tool_frequency(
    tool_call_history: list[str],
    window_size: int = WINDOW_SIZE,
    max_same_in_window: int = MAX_SAME_TOOL_IN_WINDOW,
    max_consecutive: int = MAX_CONSECUTIVE_SAME_TOOL,
) -> GuardResult:
    """
    Check whether the same tool appears too often in the recent history.

    Two triggers (either → abort):
      - Within the last *window_size* calls, the same tool appears
        ≥ *max_same_in_window* times.
      - The same tool has been called ≥ *max_consecutive* times in a row.
    """
    if not tool_call_history:
        return GuardResult()

    # --- consecutive check ------------------------------------------------
    recent = tool_call_history[-max_consecutive:]
    if len(recent) >= max_consecutive and len(set(recent)) == 1:
        tool = recent[0]
        return GuardResult(
            aborted=True,
            reason="loop_detected",
            detail={
                "trigger": "consecutive_same_tool",
                "tool": tool,
                "consecutive_count": len(recent),
                "threshold": max_consecutive,
            },
        )

    # --- sliding-window check --------------------------------------------
    window = tool_call_history[-window_size:]
    if len(window) >= window_size:
        counts: dict[str, int] = {}
        for t in window:
            counts[t] = counts.get(t, 0) + 1
        max_count = max(counts.values())
        if max_count >= max_same_in_window:
            culprit = [t for t, c in counts.items() if c == max_count][0]
            return GuardResult(
                aborted=True,
                reason="loop_detected",
                detail={
                    "trigger": "frequency_in_window",
                    "tool": culprit,
                    "count": max_count,
                    "window_size": window_size,
                    "threshold": max_same_in_window,
                },
            )

    return GuardResult()


# ---------------------------------------------------------------------------
# Layer 3: State fingerprint
# ---------------------------------------------------------------------------

def detect_loop_by_fingerprint(
    fingerprint_history: list[str],
    max_repeat: int = MAX_FINGERPRINT_REPEAT,
) -> GuardResult:
    """
    Check whether the same state fingerprint appears too many times
    consecutively, indicating the Agent isn't making progress.
    """
    if len(fingerprint_history) < max_repeat:
        return GuardResult()

    last_n = fingerprint_history[-max_repeat:]
    if len(set(last_n)) == 1:
        return GuardResult(
            aborted=True,
            reason="loop_detected",
            detail={
                "trigger": "repeated_state_fingerprint",
                "fingerprint": last_n[0],
                "repeat_count": len(last_n),
                "threshold": max_repeat,
            },
        )

    return GuardResult()


# ---------------------------------------------------------------------------
# Layer 4: Consecutive errors (result-driven stopper)
# ---------------------------------------------------------------------------

def detect_loop_by_errors(
    execution_trace: list[dict[str, Any]],
    max_consecutive: int = MAX_CONSECUTIVE_ERRORS,
) -> GuardResult:
    """
    Detect loop by counting consecutive failed steps.

    Unlike frequency/fingerprint detection, this is purely result-driven:
    regardless of which tool was called or what parameters were used,
    if the Agent fails N times in a row, it's stuck.

    The count resets on the first successful step (looking backwards from
    the most recent step).
    """
    if not execution_trace:
        return GuardResult()

    consecutive = 0
    for step in reversed(execution_trace):
        if not step.get("success", True):
            consecutive += 1
        else:
            break  # a recent success resets the counter

    if consecutive >= max_consecutive:
        return GuardResult(
            aborted=True,
            reason="loop_detected",
            detail={
                "trigger": "consecutive_errors",
                "consecutive_error_count": consecutive,
                "threshold": max_consecutive,
            },
        )

    return GuardResult()


# ---------------------------------------------------------------------------
# Layer 5: TF-IDF embedding stopper (multi-cycle pattern detection)
# ---------------------------------------------------------------------------

def _textify_step(step: dict[str, Any]) -> str:
    """Serialize one execution_trace step to text for TF-IDF embedding."""
    tool = step.get("tool", "unknown")
    result = str(step.get("result", ""))[:200]
    error = str(step.get("error", ""))[:100]
    parts = [tool]
    if result and result.strip():
        parts.append(result)
    if error and error.strip():
        parts.append(f"error:{error}")
    return " ".join(parts)


def detect_loop_by_embedding(
    execution_trace: list[dict[str, Any]],
    window_size: int = EMBED_WINDOW_SIZE,
    patience: int = EMBED_PATIENCE,
    threshold: float = EMBED_SIMILARITY_THRESHOLD,
) -> GuardResult:
    """
    Detect multi-cycle semantic loops using TF-IDF embedding + cosine similarity.

    Unlike tool-frequency detection (which only catches single-tool loops),
    this detects patterns like A→B→C→A→B→C where no single tool dominates
    but the overall behavior pattern is stagnant.

    Uses char-level TF-IDF (scikit-learn) — no GPU, no API, ~1-5ms per call.

    Parameters:
        execution_trace: list of {"tool", "success", "result", "error"} dicts.
        window_size: number of consecutive steps in each sliding window.
        patience: number of consecutive high-similarity windows before trigger.
        threshold: cosine similarity above which two windows are "similar".
    """
    if len(execution_trace) < window_size + patience:
        return GuardResult()

    # Serialize each step to text
    texts = [_textify_step(s) for s in execution_trace]

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np

        vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4))
        tfidf = vectorizer.fit_transform(texts)

        consecutive_high = 0
        best_similarity = 0.0

        for i in range(len(texts) - window_size):
            win_a = tfidf[i : i + window_size].mean(axis=0)
            win_a_dense = np.asarray(win_a).reshape(1, -1)

            win_b = tfidf[i + 1 : i + 1 + window_size].mean(axis=0)
            win_b_dense = np.asarray(win_b).reshape(1, -1)

            sim = float(cosine_similarity(win_a_dense, win_b_dense)[0][0])
            best_similarity = max(best_similarity, sim)

            if sim > threshold:
                consecutive_high += 1
            else:
                consecutive_high = 0

            if consecutive_high >= patience:
                return GuardResult(
                    aborted=True,
                    reason="loop_detected",
                    detail={
                        "trigger": "embedding_similarity",
                        "similarity": round(sim, 4),
                        "consecutive_high": consecutive_high,
                        "window_size": window_size,
                        "patience": patience,
                        "threshold": threshold,
                    },
                )

    except ImportError:
        # sklearn not available — skip this layer gracefully
        pass

    return GuardResult()


# ---------------------------------------------------------------------------
# Composite guard
# ---------------------------------------------------------------------------

def detect_loop(
    tool_call_history: list[str],
    fingerprint_history: list[str],
    iteration_count: int,
    execution_trace: list[dict[str, Any]] | None = None,
) -> GuardResult:
    """
    Composite guard: run all checks and return the *first* abort.

    Priority (fast → slow, deterministic → statistical):
      1. max_iterations_exceeded     (hard cap, instant)
      2. tool-frequency loop          (consecutive or window, ~0.1ms)
      3. fingerprint repeat loop      (stale state, ~0.5ms)
      4. consecutive errors           (result-driven, ~0.1ms)
      5. TF-IDF embedding similarity  (multi-cycle semantic, ~1-5ms)
    """
    # 1. Hard cap
    result = check_max_iterations(iteration_count)
    if result.aborted:
        return result

    # 2. Tool frequency (deterministic)
    result = detect_loop_by_tool_frequency(tool_call_history)
    if result.aborted:
        return result

    # 3. State fingerprint (deterministic)
    result = detect_loop_by_fingerprint(fingerprint_history)
    if result.aborted:
        return result

    # 4. Consecutive errors (result-driven)
    if execution_trace:
        result = detect_loop_by_errors(execution_trace)
        if result.aborted:
            return result

    # 5. TF-IDF embedding (statistical, multi-cycle)
    if execution_trace:
        result = detect_loop_by_embedding(execution_trace)
        if result.aborted:
            return result

    return GuardResult()


__all__ = [
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
    "detect_loop_by_errors",
    "detect_loop_by_embedding",
]
