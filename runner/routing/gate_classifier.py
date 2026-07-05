"""
Gate Classifier — minimal logistic regression for human_gate decisions.

Learns from labeled RLHF data when to trigger human_gate.
No external ML dependencies — pure Python with math only.

Training labels (4 types from RLHF feedback):
  - gate + human confirmed high risk     → label = 1
  - gate + human override approved       → label = 0  (false positive)
  - no gate + outcome OK                 → label = 0  (correct pass)
  - no gate + post-hoc should have gated → label = 1  (miss)

Persistence:
  clf.save("model.json")      # ── weights + bias + metadata → JSON
  clf.load("model.json")      # ── restore from file
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Feature definition
# ---------------------------------------------------------------------------

FEATURE_NAMES = [
    "tail_risk_var_99",
    "max_drawdown",
    "volatility",
    "position_limit",
    "correlation_with_existing",
    "var_99_trend",          # delta over recent steps
    "max_drawdown_trend",
]


def extract_features(risk_metrics: dict[str, Any]) -> list[float]:
    """Extract a fixed-length feature vector from risk metrics dict."""
    vec = []
    for name in FEATURE_NAMES:
        val = risk_metrics.get(name, 0.0)
        vec.append(float(val) if val is not None else 0.0)
    return vec


# ---------------------------------------------------------------------------
# GateClassifier
# ---------------------------------------------------------------------------

class GateClassifier:
    """Binary logistic regression classifier for risk gate decisions.

    Usage:
        clf = GateClassifier()
        clf.train(labeled_data)           # fit from labeled RLHF records
        prob, reason = clf.predict(risk_features)  # predict
    """

    def __init__(self) -> None:
        self.weights: list[float] = []
        self.bias: float = 0.0
        self._trained: bool = False

    # ------------------------------------------------------------------
    # Core math
    # ------------------------------------------------------------------

    @staticmethod
    def _sigmoid(z: float) -> float:
        # clamp to avoid overflow
        if z > 50:
            return 1.0
        if z < -50:
            return 0.0
        return 1.0 / (1.0 + math.exp(-z))

    def _score(self, features: list[float]) -> float:
        """Linear score: w·x + b."""
        if not self._trained:
            raise RuntimeError("Classifier not trained. Call train() first.")
        return sum(w * x for w, x in zip(self.weights, features, strict=True)) + self.bias

    # ------------------------------------------------------------------
    # Train
    # ------------------------------------------------------------------

    def train(
        self,
        labeled_data: list[dict[str, Any]],
        *,
        lr: float = 0.01,
        epochs: int = 200,
    ) -> dict[str, Any]:
        """
        Fit logistic regression via SGD on labeled RLHF data.

        Each record in `labeled_data` must have:
          - risk_features: dict  (raw risk metrics)
          - label: int          (0 = no gate needed, 1 = gate needed)

        Returns training report dict.
        """
        if not labeled_data:
            raise ValueError("labeled_data must not be empty")

        n_features = len(FEATURE_NAMES)
        self.weights = [0.0] * n_features
        self.bias = 0.0
        self._trained = True

        X = [extract_features(d["risk_features"]) for d in labeled_data]
        y = [float(d["label"]) for d in labeled_data]
        n = len(X)

        for epoch in range(epochs):
            total_loss = 0.0
            for i in range(n):
                z = self._score(X[i])
                p = self._sigmoid(z)
                err = p - y[i]       # gradient of binary cross-entropy
                total_loss += -y[i] * math.log(max(p, 1e-12)) - (1 - y[i]) * math.log(max(1 - p, 1e-12))

                # SGD update
                for j in range(n_features):
                    self.weights[j] -= lr * err * X[i][j]
                self.bias -= lr * err

            avg_loss = total_loss / n
            if epoch % 50 == 0 or epoch == epochs - 1:
                pass  # silent training; report only at end

        # Evaluate on training set
        preds = [int(self.predict(d["risk_features"])[0] > 0.5) for d in labeled_data]
        correct = sum(1 for p, t in zip(preds, y) if p == int(t))

        return {
            "accuracy": correct / n,
            "n_samples": n,
            "features": FEATURE_NAMES,
            "weights": dict(zip(FEATURE_NAMES, self.weights, strict=False)),
            "bias": self.bias,
        }

    # ------------------------------------------------------------------
    # Persist / load
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> Path:
        """Save trained weights, bias and metadata to a JSON file.

        Returns the absolute path written to.
        """
        if not self._trained:
            raise RuntimeError("Classifier not trained. Nothing to save.")
        target = Path(path).resolve()
        payload = {
            "version": 1,
            "algorithm": "logistic",
            "features": FEATURE_NAMES,
            "weights": self.weights,
            "bias": self.bias,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def load(self, path: str | Path) -> None:
        """Restore weights and bias from a previously saved model JSON file."""
        target = Path(path).resolve()
        payload = json.loads(target.read_text(encoding="utf-8"))

        stored_features = payload.get("features", [])
        if stored_features != FEATURE_NAMES:
            raise ValueError(
                f"Feature mismatch: model expects {FEATURE_NAMES}, "
                f"file contains {stored_features}"
            )

        self.weights = payload["weights"]
        self.bias = payload["bias"]
        self._trained = True

    def predict(self, risk_features: dict[str, Any]) -> tuple[float, str]:
        """
        Predict gate probability from risk metrics.

        Returns (probability, reason_string).
        """
        if not self._trained:
            raise RuntimeError("Classifier not trained. Call train() first.")

        feats = extract_features(risk_features)
        prob = self._sigmoid(self._score(feats))

        # Build a human-readable reason
        contributors: list[str] = []
        for name, w, x in zip(FEATURE_NAMES, self.weights, feats, strict=True):
            if abs(w * x) > 0.1:
                contributors.append(f"{name}={x:.3f}(w={w:+.3f})")
        reason = "GateClassifier: " + (", ".join(contributors[:5]) if contributors else "all features nominal")

        return prob, reason


# ---------------------------------------------------------------------------
# Label extraction helpers
# ---------------------------------------------------------------------------

def _reward_key_to_label(reward_key: str) -> int | None:
    """Map RLHF reward keys to binary labels. Returns None for non-gate events."""
    mapping = {
        "gate_correct": 1,
        "gate_false_positive": 0,
        "gate_miss": 1,
        "continue_correct": 0,
        "tool_success": 0,
        "tool_failure": 0,
        "human_gate_approved": 1,
        "human_gate_rejected": 0,
    }
    return mapping.get(reward_key)


def load_rlhf_dataset(
    rlhf_path: str | Path,
) -> list[dict[str, Any]]:
    """Load labeled training data from an RLHF JSONL log file.

    Each line is a JSON object written by ``rlhf_logger.log_rlhf_entry``.
    Lines whose ``reward_key`` maps to a label (0 or 1) AND whose
    ``metadata.risk_features`` are present are included.

    Returns a list of ``{"risk_features": dict, "label": int}`` dicts
    suitable for ``GateClassifier.train()``.
    """
    target = Path(rlhf_path).resolve()
    if not target.exists():
        raise FileNotFoundError(f"RLHF data file not found: {target}")

    dataset: list[dict[str, Any]] = []
    with open(target, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            reward_key = record.get("reward_key", "")
            label = _reward_key_to_label(reward_key)
            if label is None:
                continue

            # risk_features may live under metadata.risk_features
            # or directly under the record root
            risk_features = (
                record.get("metadata", {}).get("risk_features")
                or record.get("risk_features")
                or {}
            )
            if not risk_features:
                continue

            dataset.append({"risk_features": risk_features, "label": label})

    return dataset
