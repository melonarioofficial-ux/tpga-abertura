from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, VotingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score, matthews_corrcoef
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


@dataclass
class PredictionFrame:
    frame: pd.DataFrame
    feature_columns: List[str]
    class_labels: List[str]


def make_classifier(random_state: int = 42, calibration_cv: int | None = 3):
    # Ensemble intencionalmente conservador: logistica calibravel + arvores nao lineares.
    logit = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=random_state)),
    ])

    # HistGradientBoostingClassifier tem tratamento nativo de NaN; sem SimpleImputer.
    gb = Pipeline([
        ("model", HistGradientBoostingClassifier(
            max_depth=2,
            max_iter=300,
            learning_rate=0.05,
            min_samples_leaf=10,
            l2_regularization=1.0,
            class_weight="balanced",
            random_state=random_state,
        )),
    ])

    rf = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("model", RandomForestClassifier(
            n_estimators=200,
            min_samples_leaf=5,
            class_weight="balanced_subsample",
            random_state=random_state,
            n_jobs=1,
        )),
    ])

    base_ensemble = VotingClassifier(
        estimators=[("logit", logit), ("gb", gb), ("rf", rf)],
        voting="soft",
        weights=[2, 2, 1],
    )
    # Calibracao isotonica via CV. Se nao houver amostras suficientes por classe
    # para um CV valido (calibration_cv None ou < 2), retorna o ensemble nao calibrado.
    if calibration_cv is None or calibration_cv < 2:
        return base_ensemble
    return CalibratedClassifierCV(base_ensemble, method="isotonic", cv=calibration_cv)


def fit_predict_proba(train: pd.DataFrame, test: pd.DataFrame, feature_columns: List[str], random_state: int = 42) -> PredictionFrame:
    train = train.copy()
    test = test.copy()
    y_train = train["direction"].astype(str)
    if y_train.nunique() < 2:
        # Fallback honesto para janelas degeneradas.
        prior = y_train.value_counts(normalize=True).to_dict()
        labels = sorted(["down", "flat", "up"])
        for label in labels:
            test[f"p_{label}"] = prior.get(label, 0.0)
        return PredictionFrame(test, feature_columns, labels)

    # Define um CV de calibracao seguro: no maximo 3, limitado pela menor classe.
    min_class_count = int(y_train.value_counts().min())
    calibration_cv = min(3, min_class_count)
    clf = make_classifier(random_state=random_state, calibration_cv=calibration_cv)
    clf.fit(train[feature_columns], y_train)
    labels = list(clf.classes_)
    proba = clf.predict_proba(test[feature_columns])
    for i, label in enumerate(labels):
        test[f"p_{label}"] = proba[:, i]
    for label in ["down", "flat", "up"]:
        if f"p_{label}" not in test.columns:
            test[f"p_{label}"] = 0.0
    return PredictionFrame(test, feature_columns, labels)


def add_decision_columns(df: pd.DataFrame, edge_threshold: float = 0.12, confidence_threshold: float = 0.48, fakeout_max: float = 0.70, cost_points: float = 2.0, median_abs_gap: float | None = None) -> pd.DataFrame:
    out = df.copy()
    for col in ["p_up", "p_down", "p_flat"]:
        if col not in out.columns:
            out[col] = 0.0
    out["edge"] = out["p_up"] - out["p_down"]
    out["confidence"] = out[["p_up", "p_down", "p_flat"]].max(axis=1)
    # Evita lookahead: usa magnitude tipica de gap estimada no treino (median_abs_gap),
    # nao o gap realizado (futuro). Fallback para a mediana do proprio frame.
    if median_abs_gap is None:
        median_abs_gap = float(out["gap_points"].abs().median())
    out["expected_gap_points_proxy"] = out["edge"] * median_abs_gap
    out["side"] = np.where(out["edge"] > 0, 1, np.where(out["edge"] < 0, -1, 0))
    out["study_candidate"] = (
        (out["edge"].abs() >= edge_threshold)
        & (out["confidence"] >= confidence_threshold)
        & (out.get("fakeout_risk", pd.Series(0, index=out.index)).fillna(0) <= fakeout_max)
        & (out["expected_gap_points_proxy"].abs() > cost_points)
    )
    return out


def baseline_predictions(test: pd.DataFrame, train: pd.DataFrame) -> pd.DataFrame:
    out = test.copy()
    majority = train["direction"].mode().iloc[0] if len(train) else "flat"
    for label in ["down", "flat", "up"]:
        out[f"base_majority_p_{label}"] = 1.0 if label == majority else 0.0

    fut = out.get("futures_overnight_ret", pd.Series(0, index=out.index)).fillna(0)
    out["base_futures_pred"] = np.where(fut > 0, "up", np.where(fut < 0, "down", "flat"))
    close = out.get("last_5m_ret", pd.Series(0, index=out.index)).fillna(0)
    out["base_close_pred"] = np.where(close > 0, "up", np.where(close < 0, "down", "flat"))
    return out
