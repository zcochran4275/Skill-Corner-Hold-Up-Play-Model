"""Models: expected pass completion calibration, expected retention (xR) and expected EPV value.

Expected retention (xR) is the chance an average striker keeps the ball given the situation. It is the average of a
logistic regression and a small boosted-tree model. Both are trained on the situation at first contact. Applying the
same fitted model to the situation at pass release gives the odds he *inherited*:

    set-up added = xR at contact - xR at release    (what his movement before the ball arrived changed)
    duel added   = kept - xR at contact             (what he did once the ball arrived)
    retention over expected (RoE) = kept - xR at release = set-up added + duel added

Set-up added is centred on the league mean so the average striker scores 0 in both parts.
"""
import warnings

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore", category=UserWarning)

# The model features at first contact, in groups
PASS_FEATURES = ["aerial", "peak_height", "flight_s", "pass_distance", "origin_x", "xpass"]
PRESSURE_FEATURES = ["con_n5", "con_oval_sum"]
SUPPORT_FEATURES = ["sup_n_xp60", "sup_n_lane_open"]
STATE_FEATURES = ["pre_speed_con", "past_line_contact", "pre_line_height"]
FEATURES = PASS_FEATURES + PRESSURE_FEATURES + SUPPORT_FEATURES + STATE_FEATURES
FEATURE_GROUPS = {"pass": PASS_FEATURES, "pressure": PRESSURE_FEATURES, "support": SUPPORT_FEATURES, "own state": STATE_FEATURES}

# The same feature at pass release. The pass features are fixed once the ball is played, so they stay as they are.
RELEASE_VERSION = {"con_n5": "rel_n5", "con_oval_sum": "rel_oval_sum", "sup_n_xp60": "suprel_n_xp60",
                   "sup_n_lane_open": "suprel_n_lane_open", "pre_speed_con": "pre_speed_rel",
                   "past_line_contact": "line_dist_release"}

EPV_FEATURES = FEATURES + ["epv_before"]


# ---------------------------------------------------------------- building blocks

def make_logit(C=0.5):
    """Logistic regression with median imputation and standardised inputs."""
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=C, max_iter=2000))


def make_trees(seed=0):
    """Small, heavily regularised boosted trees (few leaves, shrinkage, row and column subsampling)."""
    return LGBMClassifier(n_estimators=150, learning_rate=0.03, num_leaves=4, min_child_samples=25, subsample=0.8,
                          subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, verbose=-1, random_state=seed)


def release_state(table):
    """The feature table with the state features taken at pass release instead of first contact."""
    release = table[FEATURES].copy()
    for contact_name, release_name in RELEASE_VERSION.items():
        release[contact_name] = table[release_name]
    return release


def score(y, p):
    """Log loss, Brier score and AUC of predicted probabilities p for outcomes y."""
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return dict(log_loss=log_loss(y, p, labels=[0, 1]), brier=brier_score_loss(y, p), auc=roc_auc_score(y, p))


def calibration_table(y, p, bins=6):
    """Mean predicted vs observed rate in equal-count bins of the prediction."""
    d = pd.DataFrame({"y": np.asarray(y), "p": np.asarray(p)})
    d["bin"] = pd.qcut(d.p.rank(method="first"), bins, labels=False)
    return d.groupby("bin").agg(predicted=("p", "mean"), observed=("y", "mean"), n=("y", "size"))


def calibration_slope(y, p):
    """Slope and intercept of the logit of the prediction against the outcome (1 and 0 = perfectly calibrated)."""
    p = np.clip(np.asarray(p), 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p)).reshape(-1, 1)
    fit = LogisticRegression(C=1e6, max_iter=1000).fit(z, np.asarray(y))
    return float(fit.coef_[0, 0]), float(fit.intercept_[0])


def cross_validated_predict(X, y, groups, make_model, other=None, n_splits=10, repeats=5, seed=0):
    """Out-of-fold probabilities. Folds are grouped by match, so no hold-up is scored by a model that saw its match.

    The fold assignment is repeated ``repeats`` times and the predictions averaged. ``other`` is a second table with
    the same rows and columns (for example the release state): each row of it is predicted by the same fold model
    that did not see its match. Returns the predictions, or (predictions, predictions for other).
    """
    y = np.asarray(y)
    predictions = np.zeros(len(X))
    predictions_other = np.zeros(len(X)) if other is not None else None
    for r in range(repeats):
        folds = GroupKFold(n_splits=n_splits, shuffle=True, random_state=seed + r).split(X, y, groups)
        for train, test in folds:
            model = make_model()
            model.fit(X.iloc[train], y[train])
            predictions[test] += model.predict_proba(X.iloc[test])[:, 1] / repeats
            if other is not None:
                predictions_other[test] += model.predict_proba(other.iloc[test])[:, 1] / repeats
    if other is None:
        return predictions
    return predictions, predictions_other


# ---------------------------------------------------------------- expected pass completion calibration

def _logit_of(p):
    p = np.clip(np.asarray(p, float), 1e-3, 1 - 1e-3)
    return np.log(p / (1 - p)).reshape(-1, 1)


def fit_platt(raw, completed):
    """Two-number logistic fit turning the raw physics value into a completion probability: (slope, intercept)."""
    fit = LogisticRegression(C=1e6, max_iter=1000).fit(_logit_of(raw), np.asarray(completed, int))
    return float(fit.coef_[0, 0]), float(fit.intercept_[0])


def apply_platt(raw, slope, intercept):
    raw = np.asarray(raw, float)
    z = slope * _logit_of(raw)[:, 0] + intercept
    return np.where(np.isnan(raw), np.nan, 1 / (1 + np.exp(-z)))


def calibrate_xpass_out_of_fold(raw, completed, groups, n_splits=10, repeats=3, seed=0):
    """Out-of-fold calibration of the raw physics value, so that each hold-up is scored by a fit that never saw its match."""
    raw, completed, groups = np.asarray(raw, float), np.asarray(completed, int), np.asarray(groups)
    have = ~np.isnan(raw)
    z, y, g = _logit_of(raw[have]), completed[have], groups[have]
    calibrated = np.zeros(have.sum())
    for r in range(repeats):
        for train, test in GroupKFold(n_splits, shuffle=True, random_state=seed + r).split(z, y, g):
            fit = LogisticRegression(C=1e6, max_iter=1000).fit(z[train], y[train])
            calibrated[test] += fit.predict_proba(z[test])[:, 1] / repeats
    out = np.full(len(raw), np.nan)
    out[have] = calibrated
    return out


# ---------------------------------------------------------------- expected EPV value

def make_value_models(seed=0):
    """Ridge regression and boosted trees for the expected value added; their average is the expectation."""
    ridge = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=30))
    trees = LGBMRegressor(n_estimators=150, learning_rate=0.03, num_leaves=4, min_child_samples=25, reg_lambda=5,
                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=seed)
    return ridge, trees


def cross_validated_value(X, y, groups, n_splits=10, repeats=5):
    """Out-of-fold expected value added, grouped by match."""
    y = np.asarray(y)
    expected = np.zeros(len(X))
    for r in range(repeats):
        for train, test in GroupKFold(n_splits, shuffle=True, random_state=r).split(X, y, groups):
            ridge, trees = make_value_models(seed=r)
            ridge.fit(X.iloc[train], y[train])
            trees.fit(X.iloc[train], y[train])
            expected[test] += (ridge.predict(X.iloc[test]) + trees.predict(X.iloc[test])) / 2 / repeats
    return expected


# ---------------------------------------------------------------- saved model

def fit_final_models(table, retained, value_added):
    """Fit every model on all the data and return them in one dictionary (the saved model).

    ``table`` has the model features (with the calibrated ``xpass``) plus the release columns and ``epv_before``;
    ``retained`` and ``value_added`` are the outcomes (NaN rows are skipped).
    """
    keep = retained.notna().to_numpy()
    logit_model = make_logit().fit(table.loc[keep, FEATURES], retained[keep].astype(int))
    trees_model = make_trees().fit(table.loc[keep, FEATURES], retained[keep].astype(int))
    xr_contact = (logit_model.predict_proba(table[FEATURES])[:, 1] + trees_model.predict_proba(table[FEATURES])[:, 1]) / 2
    xr_release = (logit_model.predict_proba(release_state(table))[:, 1] + trees_model.predict_proba(release_state(table))[:, 1]) / 2
    keep_value = keep & value_added.notna().to_numpy()
    ridge, trees = make_value_models()
    ridge.fit(table.loc[keep_value, EPV_FEATURES], value_added[keep_value])
    trees.fit(table.loc[keep_value, EPV_FEATURES], value_added[keep_value])
    return dict(features=FEATURES, logit=logit_model, trees=trees_model, value_ridge=ridge, value_trees=trees,
                league_setup_mean=float(np.mean((xr_contact - xr_release)[keep])))


def save_model(model, path):
    joblib.dump(model, path)


def load_model(path):
    # joblib loads pickles: only open a model file that this project's training pipeline wrote
    return joblib.load(path)


def predict_results(table, labels, model):
    """Model results for events. ``table``: features (with calibrated xpass and epv_before); ``labels``: retained and
    value_added for the same events (NaN where unknown). Returns one row per event."""
    contact_table, release_table = table[FEATURES], release_state(table)
    xr_contact = (model["logit"].predict_proba(contact_table)[:, 1] + model["trees"].predict_proba(contact_table)[:, 1]) / 2
    xr_release = (model["logit"].predict_proba(release_table)[:, 1] + model["trees"].predict_proba(release_table)[:, 1]) / 2
    expected_value = (model["value_ridge"].predict(table[EPV_FEATURES]) + model["value_trees"].predict(table[EPV_FEATURES])) / 2
    return build_results(table["event_id"], table["xpass"], xr_release, xr_contact, expected_value, labels,
                         model["league_setup_mean"])


def build_results(event_id, xpass, xr_release, xr_contact, expected_value, labels, league_setup_mean):
    """Assemble the model results dataset from the predictions and the outcomes."""
    results = pd.DataFrame({"event_id": np.asarray(event_id), "xpass": np.asarray(xpass),
                            "xr_release": xr_release, "xr_contact": xr_contact})
    retained = labels["retained"].to_numpy(float)
    results["setup"] = results.xr_contact - results.xr_release
    results["setup_c"] = results.setup - league_setup_mean                 # centred on the league mean
    results["duel"] = retained - results.xr_contact
    results["roe"] = retained - results.xr_release
    results["roe_c"] = results.setup_c + results.duel                       # = roe minus the league mean set-up
    results["exp_value"] = expected_value
    results["voe"] = labels["value_added"].to_numpy(float) - expected_value
    return results
