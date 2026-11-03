"""From hold-up scores to player stats: shrinkage, uncertainty, z-scores, rates and scenarios.

A striker has only a handful of hold-ups, so his raw average is mostly luck. The hierarchical (random-effects) model
treats each striker's true level as drawn from a league-wide distribution and pulls his raw average towards the league
mean by as much as the noise warrants (strikers with few hold-ups are pulled most). The between-striker spread is not
assumed: its posterior is computed on a grid, and every draw of a striker's level includes that uncertainty.

Scores are fractions (0.05 = 5 points per 100 hold-ups). A striker is identified by ``key`` = "player | team".
"""
import json

import numpy as np
import pandas as pd
from scipy import optimize, special, stats

from .paths import RAW_DIR

METRICS = {"roe_c": "retention over expected", "setup_c": "set-up added", "duel": "duel added",
           "voe": "value over expected (EPV)", "value_added": "value added (EPV)"}
MIN_HOLDUPS = 10            # strikers with at least this many hold-ups are rated (z-scores, percentiles)
FORWARD_ROLES = {"CF", "LF", "RF"}

# Scenarios: the hard side of one measure. 'quantile' cuts are computed from the data, 'value' cuts are fixed.
SCENARIOS = {
    "Difficult passes": dict(column="xpass", hard="low", quantile=1 / 3),    # lowest third of expected pass completion
    "High pressure": dict(column="con_oval_sum", hard="high", value=0.59),   # oval pressure at first contact of 0.59+
    "Little support": dict(column="sup_n_xp60", hard="low", value=1),        # at most one teammate with a 60%+ pass
    "Aerial balls": dict(column="aerial", hard="high", value=1),             # the ball is an aerial
}


# ---------------------------------------------------------------- shrinkage

def _between_grid(means, counts, within_sd):
    """Posterior of the between-striker standard deviation on a grid (flat prior). Returns (grid, probabilities)."""
    grid = np.linspace(0.0, 2 * float(means.std()) + 1e-9, 300) if len(means) > 1 else np.array([0.0, 1e-9])
    log_like = []
    for sd in grid:
        variance = sd ** 2 + within_sd ** 2 / counts
        weight = 1 / variance
        league = (weight * means).sum() / weight.sum()
        log_like.append(-0.5 * (np.log(variance) + (means - league) ** 2 / variance).sum() - 0.5 * np.log(weight.sum()))
    probability = np.exp(np.array(log_like) - max(log_like))
    return grid, probability / probability.sum()


def striker_posterior(scores, column, draws=2000, seed=5):
    """Draws of each striker's true level for one score.

    Returns (draws array: draws x strikers, keys, hold-up counts, raw means, league mean).
    """
    rng = np.random.default_rng(seed)
    grouped = scores.groupby("key")[column]
    counts, means = grouped.size(), grouped.mean()
    within_sd = np.sqrt(((scores[column] - scores.key.map(means)) ** 2).sum() / (len(scores) - len(means)))
    grid, probability = _between_grid(means, counts, within_sd)
    between_sd = rng.choice(grid, draws, p=probability)
    league_mean = scores[column].mean()
    levels = np.zeros((draws, len(counts)))
    for j, (key, n) in enumerate(counts.items()):
        pull = between_sd ** 2 / (between_sd ** 2 + within_sd ** 2 / n)       # 1 = trust his own average, 0 = league mean
        levels[:, j] = league_mean + pull * (means[key] - league_mean) + rng.normal(size=draws) * np.sqrt(pull * within_sd ** 2 / n)
    return levels, list(counts.index), counts, means, league_mean


def between_spread(scores, column):
    """Real spread between strikers for one score: median and 95th percentile of the between-striker sd, the sd of a
    single hold-up, and the intra-class correlation (share of the variance that is real striker differences)."""
    grouped = scores.groupby("key")[column]
    counts, means = grouped.size(), grouped.mean()
    within_sd = float(np.sqrt(((scores[column] - scores.key.map(means)) ** 2).sum() / max(len(scores) - len(means), 1)))
    grid, probability = _between_grid(means, counts, within_sd)
    cumulative = probability.cumsum()
    quantile = lambda q: float(grid[min(np.searchsorted(cumulative, q), len(grid) - 1)])
    median, upper = quantile(0.5), quantile(0.95)
    return dict(n_strikers=len(counts), n_holdups=int(counts.sum()), sd_between_median=median,
                sd_between_p5=quantile(0.05), sd_between_p95=upper, sd_within=within_sd,
                icc_median=median ** 2 / (median ** 2 + within_sd ** 2), icc_p95=upper ** 2 / (upper ** 2 + within_sd ** 2))


def percentile_ranks(levels):
    """Percentile (0-100) of each striker among all strikers, in every draw."""
    ranks = levels.argsort(axis=1).argsort(axis=1)
    return 100 * ranks / (levels.shape[1] - 1)


def shrink_metric(scores, column, min_holdups=MIN_HOLDUPS, draws=2000):
    """One row per striker for one score: raw mean, shrunk estimate with 90% interval, probability of being above the
    league mean, percentile among rated strikers with its interval, and z-scores. Returns (table, league mean)."""
    data = scores.dropna(subset=[column])
    levels, keys, counts, means, league_mean = striker_posterior(data, column, draws)
    table = pd.DataFrame({"n": counts.values, "raw": means.values, "shrunk": levels.mean(0),
                          "lo": np.percentile(levels, 5, axis=0), "hi": np.percentile(levels, 95, axis=0),
                          "p_above_league": (levels > league_mean).mean(0)}, index=keys)
    rated = (table.n >= min_holdups).to_numpy()
    table["pct"] = table["pct_lo"] = table["pct_hi"] = np.nan
    if rated.sum() > 1:
        ranks = percentile_ranks(levels[:, rated])
        table.loc[rated, "pct"] = ranks.mean(0)
        table.loc[rated, "pct_lo"] = np.percentile(ranks, 5, axis=0)
        table.loc[rated, "pct_hi"] = np.percentile(ranks, 95, axis=0)
    # z-scores: standardise against the shrunk estimates of the rated strikers (raw and interval ends use the same scale)
    centre, spread = table.loc[rated, "shrunk"].mean(), table.loc[rated, "shrunk"].std()
    for name in ("raw", "shrunk", "lo", "hi"):
        table["z_" + name] = np.where(rated, (table[name] - centre) / spread, np.nan)
    table["rated"] = rated
    return table, float(league_mean), levels


# ---------------------------------------------------------------- rates (hold-ups per 90)

def gamma_poisson(counts, exposure):
    """Empirical-Bayes gamma prior (shape a, rate b) for Poisson counts with the given exposure."""
    counts, exposure = np.asarray(counts, float), np.asarray(exposure, float)

    def negative_log_likelihood(log_params):
        a, b = np.exp(log_params)
        return -(special.gammaln(a + counts) - special.gammaln(a) - special.gammaln(counts + 1)
                 + a * np.log(b / (b + exposure)) + counts * np.log(exposure / (b + exposure))).sum()

    start = counts.sum() / exposure.sum()
    fit = optimize.minimize(negative_log_likelihood, np.log([2.0, 2.0 / start]), method="Nelder-Mead")
    return tuple(np.exp(fit.x))


def player_minutes(match_ids, events):
    """Minutes played and minutes his team had the ball, per player over all matches. Roster = every forward who played
    plus anyone with a hold-up, so strikers with zero hold-ups count."""
    have_holdup = set(zip(events.match_id, events.player_id))
    rows = []
    for match_id in match_ids:
        meta = json.loads((RAW_DIR / str(match_id) / f"{match_id}_match.json").read_text(encoding="utf-8"))
        teams = {meta["home_team"]["id"]: meta["home_team"]["short_name"], meta["away_team"]["id"]: meta["away_team"]["short_name"]}
        for p in meta["players"]:
            playing = p["playing_time"]["total"] if p.get("playing_time") else None
            if not playing or not playing.get("minutes_played"):
                continue
            if p["player_role"]["acronym"] in FORWARD_ROLES or (match_id, p["id"]) in have_holdup:
                rows.append(dict(match_id=match_id, player_id=p["id"], player=p["short_name"], team_id=p["team_id"],
                                 team_name=teams[p["team_id"]], games=1, minutes=playing["minutes_played"],
                                 minutes_in_possession=playing["minutes_tip"]))
    played = pd.DataFrame(rows)
    return played.groupby(["player_id", "team_id", "player", "team_name"], as_index=False)[["games", "minutes", "minutes_in_possession"]].sum()


# ---------------------------------------------------------------- hold-up z-scores and scenarios

def add_holdup_zscores(scores):
    """Hold-up-level z-scores (z_<score>) for each score, using the mean and sd over all hold-ups."""
    out = scores.copy()
    for column in list(METRICS) + ["xr_release"]:
        out["z_" + column] = (out[column] - out[column].mean()) / out[column].std()
    return out


def tag_scenarios(scores):
    """Which hold-ups fall in each scenario. Returns (True/False table, thresholds table)."""
    tags, rows = {}, []
    for name, rule in SCENARIOS.items():
        cut = rule["value"] if "value" in rule else float(scores[rule["column"]].quantile(rule["quantile"]))
        column = scores[rule["column"]]
        tags[name] = (column >= cut) if rule["hard"] == "high" else (column <= cut)
        rows.append(dict(scenario=name, column=rule["column"], hard_side=rule["hard"], cut_off=cut,
                         hold_ups=int(tags[name].sum()), share=float(tags[name].mean())))
    return pd.DataFrame(tags, index=scores.index), pd.DataFrame(rows).set_index("scenario")


def scenario_shrinkage(scores, tags, column="roe_c", draws=2000):
    """Shrink each striker's score within each scenario (and for all hold-ups) towards that scenario's league mean.

    Returns (long table: one row per striker per scenario, table of the between-striker spread per scenario).
    """
    tables, spreads = [], []
    for name in ["All hold-ups"] + list(SCENARIOS):
        subset = scores if name == "All hold-ups" else scores[tags[name]]
        subset = subset.dropna(subset=[column])
        levels, keys, counts, means, league_mean = striker_posterior(subset, column, draws)
        table = pd.DataFrame({"scenario": name, "key": keys, "n": counts.values, "raw": means.values,
                              "shrunk": levels.mean(0), "lo": np.percentile(levels, 5, axis=0),
                              "hi": np.percentile(levels, 95, axis=0), "p_above_scenario_mean": (levels > league_mean).mean(0),
                              "scenario_mean": league_mean})
        tables.append(table)
        spreads.append(dict(scenario=name, league_mean=league_mean, **between_spread(subset, column)))
    return pd.concat(tables, ignore_index=True), pd.DataFrame(spreads).set_index("scenario")


# ---------------------------------------------------------------- the player stats table

def build_player_stats(scores, minutes, min_holdups=MIN_HOLDUPS, draws=2000, seed=11):
    """One row per striker: counts, minutes, rates, and for each score the shrunk estimate, interval, percentile and
    z-scores, plus the score per 90 minutes.

    ``scores`` has one row per hold-up with key, player_id, team_id, retained, xr_release and the five METRICS.

    Per 90 minutes: a striker's total contribution is (his level per hold-up) x (his hold-ups per 90). Both are
    uncertain, so each draw of his level (from the shrinkage model) is multiplied by an independent draw of his rate
    (from the gamma-Poisson posterior, which uses his minutes played). The shrunk per-90 value, its 90% interval and the
    probability of being above the league are taken from the product draws. Units: the score's own units per 90 minutes
    (for example extra kept hold-ups per 90 for retention over expected).
    """
    rng = np.random.default_rng(seed)
    people = scores.groupby("key").agg(player=("player", "first"), team_name=("team_name", "first"),
                                       player_id=("player_id", "first"), team_id=("team_id", "first"),
                                       n_holdups=("retained", "size"), retention=("retained", "mean"),
                                       service_xr=("xr_release", "mean"))
    # rates: hold-ups per 90 for every forward on the roster, shrunk with a gamma-Poisson model on minutes played
    rates = minutes.merge(people[["player_id", "team_id", "n_holdups"]], on=["player_id", "team_id"], how="left")
    rates["n_holdups"] = rates.n_holdups.fillna(0)
    a, b = gamma_poisson(rates.n_holdups, rates.minutes)
    rates["rate_shape"], rates["rate_rate"] = a + rates.n_holdups, b + rates.minutes
    rates["holdups_per_game"] = rates.n_holdups / rates.games
    rates["holdups_per90"] = rates.n_holdups / rates.minutes * 90
    rates["holdups_per90_shrunk"] = rates.rate_shape / rates.rate_rate * 90
    rates["holdups_per90_lo"] = stats.gamma.ppf(0.05, rates.rate_shape, scale=1 / rates.rate_rate) * 90
    rates["holdups_per90_hi"] = stats.gamma.ppf(0.95, rates.rate_shape, scale=1 / rates.rate_rate) * 90
    league_rate90 = rates.n_holdups.sum() / rates.minutes.sum() * 90
    posterior = rates.set_index(["player_id", "team_id"])

    stats_table = people
    for column in METRICS:
        table, league_mean, levels = shrink_metric(scores, column, min_holdups, draws)
        ids = people.loc[table.index]
        index = list(zip(ids.player_id, ids.team_id))
        shape, rate = posterior.loc[index, "rate_shape"].to_numpy(), posterior.loc[index, "rate_rate"].to_numpy()
        per90 = levels * rng.gamma(shape[None, :], 1 / rate[None, :], size=levels.shape) * 90
        league_per90 = league_mean * league_rate90
        table["per90"] = per90.mean(0)
        table["per90_lo"], table["per90_hi"] = np.percentile(per90, 5, axis=0), np.percentile(per90, 95, axis=0)
        table["per90_p_above_league"] = (per90 > league_per90).mean(0)
        rated = table.rated.to_numpy()
        table["per90_z_shrunk"] = np.where(rated, (table.per90 - table.per90[rated].mean()) / table.per90[rated].std(), np.nan)
        table = table.drop(columns=["n", "rated"]).add_prefix(column + "_")
        table[column + "_league_mean"] = league_mean
        table[column + "_league_per90"] = league_per90
        stats_table = stats_table.join(table)
    stats_table["rated"] = stats_table.n_holdups >= min_holdups
    stats_table = stats_table.reset_index()
    rate_columns = ["player_id", "team_id", "games", "minutes", "minutes_in_possession", "holdups_per_game", "holdups_per90",
                    "holdups_per90_shrunk", "holdups_per90_lo", "holdups_per90_hi"]
    return stats_table.merge(rates[rate_columns], on=["player_id", "team_id"], how="left")
