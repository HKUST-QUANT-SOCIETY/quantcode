"""
XGBoost Gate Classifier — gradient-boosted risk gate decisions.

Provides an XGBoost alternative to the logistic regression ``GateClassifier``.
Shares the same feature set and prediction interface so it can be used as a
drop-in replacement in ``combined_router._resolve_gate_classifier``.

Unlike the pure-Python LR, this module requires the ``xgboost`` package::

    pip install xgboost

Training labels (4 types from RLHF feedback):
  - gate + human confirmed high risk     → label = 1
  - gate + human override approved       → label = 0  (false positive)
  - no gate + outcome OK                 → label = 0  (correct pass)
  - no gate + post-hoc should have gated → label = 1  (miss)

Persistence:
  clf.save("model.json")     # ── XGBoost JSON (ultra-fast dump)
  clf.load("model.json")     # ── restore from file
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import xgboost as xgb

from .gate_classifier import FEATURE_NAMES, extract_features


# ---------------------------------------------------------------------------
# XGBoost Gate Classifier
# ---------------------------------------------------------------------------

class XGBGateClassifier:
    """XGBoost binary classifier for risk gate decisions.

    Same interface as ``GateClassifier`` so callers can swap implementations
    without changing any code::

        from runner.routing.xgb_classifier import XGBGateClassifier
        clf = XGBGateClassifier()
        clf.train(labeled_data)
        prob, reason = clf.predict(risk_features)
        clf.save(".quantcode/gate_classifier_model.json")
    """

    def __init__(self) -> None:
        self._model: xgb.Booster | None = None
        self._trained: bool = False

        # Feature importance cache — populated after train()
        self.feature_importance: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Train
    # ------------------------------------------------------------------

    def train(
        self,
        labeled_data: list[dict[str, Any]],
        *,
        num_rounds: int = 100,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Fit XGBoost classifier on labeled RLHF data.

        Parameters:
          labeled_data: list of ``{"risk_features": dict, "label": 0/1}``
          num_rounds: number of boosting rounds
          **kwargs: forwarded to ``xgb.train`` (e.g. ``max_depth=4``)

        Returns training report dict.
        """
        if not labeled_data:
            raise ValueError("labeled_data must not be empty")

        n_features = len(FEATURE_NAMES)
        X = [extract_features(d["risk_features"]) for d in labeled_data]
        y = [float(d["label"]) for d in labeled_data]
        n = len(X)

        dtrain = xgb.DMatrix(X, label=y, feature_names=FEATURE_NAMES)

        # Sensible defaults for a small tabular dataset
        params: dict[str, Any] = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "max_depth": kwargs.pop("max_depth", 4),
            "learning_rate": kwargs.pop("learning_rate", 0.1),
            "subsample": kwargs.pop("subsample", 0.8),
            "colsample_bytree": kwargs.pop("colsample_bytree", 0.8),
            "seed": kwargs.pop("seed", 42),
        }
        params.update(kwargs)

        self._model = xgb.train(
            params,
            dtrain,
            num_boost_round=num_rounds,
            verbose_eval=False,
        )
        self._trained = True

        # Cache feature importance
        importance = self._model.get_score(importance_type="gain")
        self.feature_importance = {
            name: float(importance.get(name, 0.0))
            for name in FEATURE_NAMES
        }

        # Evaluate on training set
        preds = self._model.predict(dtrain)
        pred_labels = [int(p > 0.5) for p in preds]
        correct = sum(1 for p, t in zip(pred_labels, y) if p == int(t))

        return {
            "algorithm": "xgboost",
            "accuracy": correct / n,
            "n_samples": n,
            "features": FEATURE_NAMES,
            "num_rounds": num_rounds,
            "params": params,
            "feature_importance": self.feature_importance,
        }

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict(self, risk_features: dict[str, Any]) -> tuple[float, str]:
        """Predict gate probability from risk metrics.

        Returns ``(probability, reason_string)``.
        """
        if not self._trained or self._model is None:
            raise RuntimeError("Classifier not trained. Call train() first.")

        feats = extract_features(risk_features)
        dtest = xgb.DMatrix([feats], feature_names=FEATURE_NAMES)
        prob = float(self._model.predict(dtest)[0])

        # Build human-readable reason using feature importance × value
        contributors: list[str] = []
        for name, x in zip(FEATURE_NAMES, feats, strict=True):
            imp = self.feature_importance.get(name, 0.0)
            if imp > 0 and abs(x) > 0.01:
                contributors.append(f"{name}={x:.3f}(imp={imp:.1f})")

        # Sort by importance descending and take top 5
        contributors.sort(
            key=lambda c: float(c.split("(imp=")[1].rstrip(")")),
            reverse=True,
        )
        reason = "XGBGateClassifier: " + (
            ", ".join(contributors[:5]) if contributors else "all features nominal"
        )

        return prob, reason

    # ------------------------------------------------------------------
    # Persist / load
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> Path:
        """Save XGBoost model + metadata to a JSON file.

        Returns the absolute path written to.
        """
        if not self._trained or self._model is None:
            raise RuntimeError("Classifier not trained. Nothing to save.")

        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        # XGBoost native JSON format — no pickle, human-inspectable
        raw = self._model.save_raw(raw_format="json")
        raw_str = raw if isinstance(raw, str) else raw.decode("utf-8")

        payload = {
            "version": 1,
            "algorithm": "xgboost",
            "features": FEATURE_NAMES,
            "feature_importance": self.feature_importance,
            "model": raw_str,
        }
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def load(self, path: str | Path) -> None:
        """Restore XGBoost model from a previously saved JSON file."""
        target = Path(path).resolve()
        payload = json.loads(target.read_text(encoding="utf-8"))

        # Accept either XGBoost or LR models transparently
        algorithm = payload.get("algorithm", "logistic")
        stored_features = payload.get("features", [])

        if stored_features != FEATURE_NAMES:
            raise ValueError(
                f"Feature mismatch: model expects {FEATURE_NAMES}, "
                f"file contains {stored_features}"
            )

        if algorithm == "xgboost":
            raw_model = payload["model"]
            raw = raw_model if isinstance(raw_model, bytes) else raw_model.encode("utf-8")
            self._model = xgb.Booster()
            self._model.load_model(bytearray(raw))
            self.feature_importance = payload.get("feature_importance", {})
        else:
            raise ValueError(
                f"Unsupported algorithm '{algorithm}'. "
                f"Use GateClassifier.load() for logistic regression models."
            )

        self._trained = True
