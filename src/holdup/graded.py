"""Graded outcomes: scoring a hold-up on a scale instead of kept (1) or lost (0).

Kept / lost throws away detail: a loss after 0.2 s and a loss after 2.9 s count the same, and so do a kept ball that
goes backwards and one that moves the attack on. Each graded outcome below keeps more of that detail:

  retained   1 if kept (or a foul won), 0 if lost                     (the original, for comparison)
  survival   share of the 3 s window his team kept the ball: 1 if kept, frames until the loss / 30 if lost
  epv        SkillCorner EPV added by the hold-up (value added)
  tiered     lost: 0.5 x survival (0 to 0.5); kept but EPV did not improve: 0.75; kept and EPV improved, or foul won: 1
  blend      retained and epv, each standardised, added together

For every outcome an expected value given the situation is learned (out of fold, grouped by match), at first contact
and at pass release, and the over-expected score is  outcome - expected at release  (like retention over expected).
"""
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from . import model

OUTCOMES = {
    "retained": "kept (1) or lost (0)",
    "survival": "share of the 3 s the ball was kept",
    "epv": "EPV added by the hold-up",
    "tiered": "lost early < lost late < kept < kept and advanced",
    "blend": "retained + EPV added (each standardised)",
}
WINDOW_FRAMES = 30


def build_outcomes(events):
    """The graded outcomes for each event (needs result, frames_to_loss, retained, value_added). Rows without an
    outcome (own shots) stay NaN."""
    out = pd.DataFrame({"event_id": events.event_id.to_numpy()})
    scored = events.retained.notna().to_numpy()
    lost_survival = (events.frames_to_loss.fillna(0) / WINDOW_FRAMES).clip(0, 1)
    survival = np.where(events.retained == 1, 1.0, lost_survival)
    advanced = events.value_added > 0
    tiered = np.where(events.retained == 1, np.where((events.result == "foul_won") | advanced, 1.0, 0.75),
                      0.5 * lost_survival)
    out["retained"] = events.retained.to_numpy()
    out["survival"] = np.where(scored, survival, np.nan)
    out["epv"] = events.value_added.to_numpy()
    out["tiered"] = np.where(scored & events.value_added.notna(), tiered, np.nan)
    both = scored & events.value_added.notna().to_numpy()
    z_retained = (events.retained - events.retained[both].mean()) / events.retained[both].std()
    z_epv = (events.value_added - events.value_added[both].mean()) / events.value_added[both].std()
    out["blend"] = np.where(both, z_retained + z_epv, np.nan)
    return out


def cross_validated_regression(X, y, groups, other, n_splits=10, repeats=5):
    """Out-of-fold expected outcome (ridge + boosted trees averaged) at the situation in X and in ``other``."""
    y = np.asarray(y, float)
    at_x, at_other = np.zeros(len(X)), np.zeros(len(X))
    for r in range(repeats):
        for train, test in GroupKFold(n_splits, shuffle=True, random_state=r).split(X, y, groups):
            ridge, trees = model.make_value_models(seed=r)
            ridge.fit(X.iloc[train], y[train])
            trees.fit(X.iloc[train], y[train])
            at_x[test] += (ridge.predict(X.iloc[test]) + trees.predict(X.iloc[test])) / 2 / repeats
            at_other[test] += (ridge.predict(other.iloc[test]) + trees.predict(other.iloc[test])) / 2 / repeats
    return at_x, at_other


def over_expected(data, outcomes, name, production_classifier=False, n_splits=10, repeats=5, context=None):
    """Over-expected scores for one outcome. ``data``: model features (with release columns, epv_before, match_id,
    event_id), aligned row by row with ``outcomes``. Returns a table with event_id, outcome, expected at contact and
    at release, ``oe_release`` (outcome - expected at release, centred on its mean) and ``oe_contact`` (outcome -
    expected at contact; the part after the ball arrives).

    ``production_classifier=True`` uses the pipeline's retention model (logistic + trees on the 13 features) for the
    binary outcome; otherwise the same ridge + trees regression is used for every outcome.

    ``context``: extra columns (same rows as ``data``, for example team indicators and the striker's pitch position)
    added to the situation at both moments, so the expectation also accounts for where and for whom the hold-up
    happens. Strikers who play for one team are then partly absorbed by the team terms.
    """
    y = outcomes[name].to_numpy(float)
    keep = ~np.isnan(y)
    d = data[keep].reset_index(drop=True)
    extra = context[keep].reset_index(drop=True) if context is not None else pd.DataFrame(index=d.index)
    yk, groups = y[keep], d.match_id.to_numpy()
    if production_classifier:
        contact_x = pd.concat([d[model.FEATURES], extra], axis=1)
        release_x = pd.concat([model.release_state(d), extra], axis=1)
        l_c, l_r = model.cross_validated_predict(contact_x, yk.astype(int), groups, model.make_logit, release_x, n_splits, repeats)
        t_c, t_r = model.cross_validated_predict(contact_x, yk.astype(int), groups, model.make_trees, release_x, n_splits, repeats)
        at_contact, at_release = (l_c + t_c) / 2, (l_r + t_r) / 2
    else:
        columns = model.EPV_FEATURES
        release = model.release_state(d)
        release["epv_before"] = d.epv_before
        at_contact, at_release = cross_validated_regression(pd.concat([d[columns], extra], axis=1), yk, groups,
                                                            pd.concat([release[columns], extra], axis=1), n_splits, repeats)
    result = pd.DataFrame({"event_id": d.event_id, "outcome": yk, "expected_contact": at_contact,
                           "expected_release": at_release})
    result["oe_release"] = result.outcome - result.expected_release
    result["oe_release"] -= result.oe_release.mean()
    result["oe_contact"] = result.outcome - result.expected_contact
    result["oe_contact"] -= result.oe_contact.mean()
    return result


def reliability(scores, column, min_holdups=10, splits=300, seed=0):
    """How repeatable the striker differences in ``column`` are. ``scores`` has one row per hold-up with ``key``.

    Returns a dict: the sd of one hold-up, the real between-striker sd and the intra-class correlation (ICC, share of
    variance that is a real striker difference), the 90% shrunk interval width in units of one hold-up's sd (so
    outcomes on different scales can be compared), strikers whose interval excludes the league mean, and the split-half
    correlation (each striker's hold-ups split at random in two, Spearman across strikers of the two averages).
    """
    from . import aggregate
    data = scores.dropna(subset=[column])
    spread = aggregate.between_spread(data, column)
    table, league_mean, _ = aggregate.shrink_metric(data, column, min_holdups, draws=1000)
    rated = table[table.rated]
    rng = np.random.default_rng(seed)
    groups = {k: g[column].to_numpy() for k, g in data.groupby("key") if len(g) >= min_holdups}
    split_half = []
    for _ in range(splits):
        first, second = [], []
        for values in groups.values():
            order = rng.permutation(len(values))
            half = len(values) // 2
            first.append(values[order[:half]].mean())
            second.append(values[order[half:]].mean())
        split_half.append(pd.Series(first).corr(pd.Series(second), method="spearman"))
    return dict(hold_ups=spread["n_holdups"], strikers=spread["n_strikers"], rated=len(rated),
                sd_one_holdup=spread["sd_within"], real_sd_median=spread["sd_between_median"],
                real_sd_p95=spread["sd_between_p95"], real_sd_over_noise=spread["sd_between_median"] / spread["sd_within"],
                icc_median=spread["icc_median"], icc_p95=spread["icc_p95"],
                interval_width_in_holdup_sd=float((rated.hi - rated.lo).median() / spread["sd_within"]),
                excluding_league=int(((rated.lo > league_mean) | (rated.hi < league_mean)).sum()),
                split_half_mean=float(np.nanmean(split_half)), split_half_p5=float(np.nanpercentile(split_half, 5)),
                split_half_p95=float(np.nanpercentile(split_half, 95)))
