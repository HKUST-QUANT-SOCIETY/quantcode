#!/usr/bin/env python
"""
Gate Classifier Training Pipeline — cold-start → train → evaluate → persist.

Reads RLHF-labeled data from the existing RLHF JSONL log (or generates
synthetic training data when no labels are available), trains both
Logistic Regression and XGBoost classifiers, selects the best model, and
saves it for ``combined_router`` to auto-load on next startup.

Usage::

    # Train with existing RLHF data (if any), fall back to synthetic:
    python scripts/train_gate_classifier.py

    # Force synthetic data only (cold start):
    python scripts/train_gate_classifier.py --synthetic

    # Specify output path:
    python scripts/train_gate_classifier.py --output .quantcode/gate_classifier_model.json

    # Compare only (don't save):
    python scripts/train_gate_classifier.py --compare-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure quantcode is on path when run as script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RLHF_PATH = ".quantcode/rlhf_data.jsonl"
DEFAULT_MODEL_PATH = ".quantcode/gate_classifier_model.json"

# ── Synthetic data templates ───────────────────────────────────────────

_LOW_RISK = {
    "tail_risk_var_99": 0.020,
    "max_drawdown": 0.060,
    "volatility": 0.100,
    "position_limit": 0.350,
    "correlation_with_existing": 0.200,
    "var_99_trend": -0.001,
    "max_drawdown_trend": 0.002,
}

_HIGH_RISK = {
    "tail_risk_var_99": 0.085,
    "max_drawdown": 0.220,
    "volatility": 0.350,
    "position_limit": 0.920,
    "correlation_with_existing": 0.700,
    "var_99_trend": 0.020,
    "max_drawdown_trend": 0.050,
}

_BORDERLINE_LOW = {
    "tail_risk_var_99": 0.045,
    "max_drawdown": 0.130,
    "volatility": 0.180,
    "position_limit": 0.750,
    "correlation_with_existing": 0.400,
    "var_99_trend": 0.008,
    "max_drawdown_trend": 0.010,
}

_BORDERLINE_HIGH = {
    "tail_risk_var_99": 0.055,
    "max_drawdown": 0.160,
    "volatility": 0.250,
    "position_limit": 0.850,
    "correlation_with_existing": 0.550,
    "var_99_trend": 0.012,
    "max_drawdown_trend": 0.018,
}


def _jitter(risk: dict[str, float], noise: float = 0.01) -> dict[str, float]:
    """Add small Gaussian-like jitter so samples aren't identical."""
    import random
    out = {}
    for k, v in risk.items():
        delta = random.uniform(-noise, noise) * (abs(v) + 0.01)
        out[k] = round(max(0.0, v + delta), 4)
    return out


def _generate_synthetic_dataset(
    n_per_class: int = 100,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Generate a balanced synthetic dataset for cold-start training.

    Produces 4 classes of samples:
      - low risk    → label 0  (safe — no gate needed)
      - high risk   → label 1  (dangerous — gate needed)
      - borderline low → label 0
      - borderline high → label 1

    Returns ``[{"risk_features": dict, "label": 0|1}, ...]``.
    """
    import random
    random.seed(seed)

    dataset: list[dict[str, Any]] = []
    for base, label, count in [
        (_LOW_RISK, 0, n_per_class),
        (_HIGH_RISK, 1, n_per_class),
        (_BORDERLINE_LOW, 0, n_per_class // 2),
        (_BORDERLINE_HIGH, 1, n_per_class // 2),
    ]:
        for _ in range(count):
            dataset.append({"risk_features": _jitter(base), "label": label})
    random.shuffle(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Load RLHF data
# ---------------------------------------------------------------------------

def _load_rlhf_dataset(rlhf_path: str) -> list[dict[str, Any]]:
    """Load labeled records from RLHF JSONL, using the same extraction
    logic as ``gate_classifier.load_rlhf_dataset``."""
    from runner.routing.gate_classifier import load_rlhf_dataset

    target = Path(rlhf_path)
    if not target.exists():
        return []

    try:
        return load_rlhf_dataset(str(target))
    except Exception as exc:
        print(f"⚠️  Failed to load RLHF data: {exc}")
        return []


# ---------------------------------------------------------------------------
# Train & compare
# ---------------------------------------------------------------------------

def _train_and_compare(
    dataset: list[dict[str, Any]],
    *,
    n_per_class: int = 100,
    seed: int = 42,
) -> dict[str, Any]:
    """Train both classifiers, return comparison report."""
    from runner.routing.gate_classifier import GateClassifier
    from runner.routing.xgb_classifier import XGBGateClassifier

    n = len(dataset)
    n_label_1 = sum(1 for d in dataset if d["label"] == 1)
    n_label_0 = n - n_label_1

    # ── Logistic Regression ──
    t0 = time.perf_counter()
    lr = GateClassifier()
    lr_report = lr.train(dataset, epochs=300)
    lr_time = time.perf_counter() - t0

    # Re-evaluate manually for precision/recall
    lr_preds = []
    for d in dataset:
        prob, _ = lr.predict(d["risk_features"])
        lr_preds.append(1 if prob > 0.5 else 0)
    lr_tp = sum(1 for p, d in zip(lr_preds, dataset) if p == 1 and d["label"] == 1)
    lr_fp = sum(1 for p, d in zip(lr_preds, dataset) if p == 1 and d["label"] == 0)
    lr_fn = sum(1 for p, d in zip(lr_preds, dataset) if p == 0 and d["label"] == 1)
    lr_precision = lr_tp / (lr_tp + lr_fp) if (lr_tp + lr_fp) > 0 else 0.0
    lr_recall = lr_tp / (lr_tp + lr_fn) if (lr_tp + lr_fn) > 0 else 0.0
    lr_f1 = (
        2 * lr_precision * lr_recall / (lr_precision + lr_recall)
        if (lr_precision + lr_recall) > 0 else 0.0
    )

    # ── XGBoost ──
    t0 = time.perf_counter()
    xgb_clf = XGBGateClassifier()
    xgb_report = xgb_clf.train(dataset, num_rounds=150)
    xgb_time = time.perf_counter() - t0

    xgb_preds = []
    for d in dataset:
        prob, _ = xgb_clf.predict(d["risk_features"])
        xgb_preds.append(1 if prob > 0.5 else 0)
    xgb_tp = sum(1 for p, d in zip(xgb_preds, dataset) if p == 1 and d["label"] == 1)
    xgb_fp = sum(1 for p, d in zip(xgb_preds, dataset) if p == 1 and d["label"] == 0)
    xgb_fn = sum(1 for p, d in zip(xgb_preds, dataset) if p == 0 and d["label"] == 1)
    xgb_precision = xgb_tp / (xgb_tp + xgb_fp) if (xgb_tp + xgb_fp) > 0 else 0.0
    xgb_recall = xgb_tp / (xgb_tp + xgb_fn) if (xgb_tp + xgb_fn) > 0 else 0.0
    xgb_f1 = (
        2 * xgb_precision * xgb_recall / (xgb_precision + xgb_recall)
        if (xgb_precision + xgb_recall) > 0 else 0.0
    )

    # ── Winner selection ──
    # Prefer recall (catch more risky situations) when F1 is close
    winner = "lr"
    if xgb_f1 > lr_f1 + 0.01:
        winner = "xgboost"
    elif abs(xgb_f1 - lr_f1) <= 0.01 and xgb_recall > lr_recall:
        winner = "xgboost"

    return {
        "dataset": {
            "total": n,
            "label_1": n_label_1,
            "label_0": n_label_0,
            "source": "synthetic" if n >= 50 else "rlhf",
        },
        "logistic_regression": {
            "accuracy": lr_report["accuracy"],
            "precision": round(lr_precision, 4),
            "recall": round(lr_recall, 4),
            "f1": round(lr_f1, 4),
            "train_time_s": round(lr_time, 3),
            "weights": lr_report.get("weights", {}),
            "bias": lr_report.get("bias", 0.0),
        },
        "xgboost": {
            "accuracy": xgb_report["accuracy"],
            "precision": round(xgb_precision, 4),
            "recall": round(xgb_recall, 4),
            "f1": round(xgb_f1, 4),
            "train_time_s": round(xgb_time, 3),
            "num_rounds": xgb_report.get("num_rounds", 0),
            "feature_importance": xgb_report.get("feature_importance", {}),
        },
        "winner": winner,
    }


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def _save_best(
    report: dict[str, Any],
    dataset: list[dict[str, Any]],
    output_path: str,
) -> Path:
    """Save the winning classifier to disk."""
    winner = report["winner"]
    target = Path(output_path).resolve()

    if winner == "xgboost":
        from runner.routing.xgb_classifier import XGBGateClassifier
        clf: Any = XGBGateClassifier()
        clf.train(dataset, num_rounds=150)
        clf.save(target)
        print(f"✅ Saved XGBoost model → {target}")
    else:
        from runner.routing.gate_classifier import GateClassifier
        clf = GateClassifier()
        clf.train(dataset, epochs=300)
        clf.save(target)
        print(f"✅ Saved Logistic Regression model → {target}")

    return target


# ---------------------------------------------------------------------------
# Print
# ---------------------------------------------------------------------------

def _print_report(report: dict[str, Any], data_source: str):
    """Pretty-print the comparison report."""
    lr = report["logistic_regression"]
    xgb = report["xgboost"]
    ds = report["dataset"]

    winner = report["winner"]
    lr_star = " ←" if winner == "lr" else ""
    xgb_star = " ←" if winner == "xgboost" else ""

    print()
    print("=" * 60)
    print("  Gate Classifier Training Report")
    print("=" * 60)
    print(f"  Data source:  {data_source}")
    print(f"  Samples:      {ds['total']}  (label=1: {ds['label_1']}, label=0: {ds['label_0']})")
    print()
    print(f"  {'Metric':<20} {'Logistic Regression':>22} {'XGBoost':>15}")
    print(f"  {'-'*20} {'-'*22} {'-'*15}")
    print(f"  {'Accuracy':<20} {lr['accuracy']:>22.4f} {xgb['accuracy']:>15.4f}")
    print(f"  {'Precision':<20} {lr['precision']:>22.4f} {xgb['precision']:>15.4f}")
    print(f"  {'Recall':<20} {lr['recall']:>22.4f} {xgb['recall']:>15.4f}")
    print(f"  {'F1 Score':<20} {lr['f1']:>22.4f} {xgb['f1']:>15.4f}")
    print(f"  {'Train time':<20} {lr['train_time_s']:>21.3f}s {xgb['train_time_s']:>14.3f}s")
    print()
    print(f"  Winner: {winner.upper()}")
    if winner == "lr":
        print(f"    LR F1={lr['f1']:.4f} >= XGBoost F1={xgb['f1']:.4f}")
        print(f"    → LR preferred: no external dependencies, fast to load")
    else:
        print(f"    XGBoost F1={xgb['f1']:.4f} > LR F1={lr['f1']:.4f}")
        if xgb["recall"] > lr["recall"]:
            print(f"    → Better recall: catches more risky situations")
    print()

    # Feature importance (XGBoost)
    fi = xgb.get("feature_importance", {})
    if fi:
        print("  XGBoost Feature Importance (gain):")
        for name, imp in sorted(fi.items(), key=lambda x: x[1], reverse=True):
            bar = "█" * max(1, int(imp / max(fi.values()) * 30)) if max(fi.values()) > 0 else ""
            print(f"    {name:<30} {imp:>10.2f}  {bar}")
        print()

    # LR weights
    lr_weights = lr.get("weights", {})
    if lr_weights:
        print("  Logistic Regression Weights:")
        for name, w in sorted(lr_weights.items(), key=lambda x: abs(x[1]), reverse=True):
            direction = "→ gate" if w > 0 else "← pass"
            print(f"    {name:<30} {w:>+10.4f}  {direction}")
        print(f"    {'bias':<30} {lr.get('bias', 0.0):>+10.4f}")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Train GateClassifier (LR + XGBoost) from RLHF/synthetic data",
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Force synthetic data (ignore RLHF log)",
    )
    parser.add_argument(
        "--compare-only", action="store_true",
        help="Train and compare but don't save a model",
    )
    parser.add_argument(
        "--output", type=str, default=DEFAULT_MODEL_PATH,
        help=f"Model output path (default: {DEFAULT_MODEL_PATH})",
    )
    parser.add_argument(
        "--rlhf-path", type=str, default=DEFAULT_RLHF_PATH,
        help=f"RLHF JSONL path (default: {DEFAULT_RLHF_PATH})",
    )
    parser.add_argument(
        "--n-synthetic", type=int, default=100,
        help="Samples per class for synthetic data (default: 100)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed (default: 42)",
    )
    args = parser.parse_args()

    # ── Load / generate data ──
    rlhf_dataset: list[dict[str, Any]] = []
    data_source = "synthetic"

    if not args.synthetic:
        rlhf_dataset = _load_rlhf_dataset(args.rlhf_path)
        if rlhf_dataset:
            data_source = f"rlhf ({args.rlhf_path})"
            print(f"📂 Loaded {len(rlhf_dataset)} labeled records from RLHF log")
        else:
            print(f"⚠️  No RLHF data found at {args.rlhf_path}")
            print("   Falling back to synthetic data for cold start...")

    # Always use synthetic for cold-start unless we have enough RLHF data
    if len(rlhf_dataset) < 10:
        synthetic = _generate_synthetic_dataset(
            n_per_class=args.n_synthetic,
            seed=args.seed,
        )
        if not rlhf_dataset:
            dataset = synthetic
        else:
            # Merge: RLHF first (higher quality), then synthetic to fill
            dataset = rlhf_dataset + synthetic
            data_source += f" + {len(synthetic)} synthetic"
        print(f"🧪 Generated {len(synthetic)} synthetic samples")
    else:
        dataset = rlhf_dataset

    print(f"   Total training set: {len(dataset)} samples")

    # ── Train & compare ──
    report = _train_and_compare(dataset, n_per_class=args.n_synthetic, seed=args.seed)
    _print_report(report, data_source)

    # ── Save ──
    if not args.compare_only:
        saved_path = _save_best(report, dataset, args.output)
        report_path = Path(args.output).with_suffix(".report.json")
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"📝 Comparison report saved → {report_path}")
        print()
        print(f"   combined_router will auto-load from: {saved_path}")
        print(f"   Set env GATE_MODEL_PATH to override.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
