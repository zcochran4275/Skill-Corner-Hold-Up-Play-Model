"""The three pipelines.

1. ``run_event_pipeline(match_id, use_model)``   detect the hold-ups of one match, extract their features and, if the
   model is on, score each one. Writes three csv files that share the key ``event_id``:
       data/events/<match_id>.csv         the event detection dataset (who, when, where, outcome, EPV)
       data/features/<match_id>.csv       the feature dataset (what the model sees)
       data/model_results/<match_id>.csv  the model results dataset (only when the model is on)
2. ``run_training_pipeline()``              trains the retention model on all matches and saves it.
3. ``run_aggregation_pipeline()``           turns the model results into one row per striker (player stats).
"""
import pandas as pd

from . import aggregate, model
from .data import list_match_ids, load_match
from .detection import detect_events
from .features import all_features
from .labels import label_outcomes, label_values
from .paths import (EVENTS_DIR, FEATURES_DIR, MODEL_PATH, PLAYERS_DIR, RESULTS_DIR, TRAINING_DIR, make_folders)


# ---------------------------------------------------------------- 1. event pipeline

def build_events(match):
    """Detect the hold-ups of a match and attach their outcome and EPV labels."""
    events = detect_events(match)
    if events.empty:
        return events
    return pd.concat([events, label_outcomes(match, events), label_values(match, events)], axis=1)


def score_events(events, features, saved_model):
    """Model results for events and features of any matches: calibrate xpass, then run the models."""
    slope, intercept = saved_model["xpass_platt"]
    table = features.merge(events[["event_id", "epv_before"]], on="event_id", how="left")
    table["xpass"] = model.apply_platt(table.xpass_raw, slope, intercept)
    return model.predict_results(table, events[["retained", "value_added"]].reset_index(drop=True), saved_model)


def run_event_pipeline(match_id, use_model=False, model_path=MODEL_PATH, save=True, match=None):
    """Detect, extract features and (optionally) score the hold-ups of one match.

    Returns a dict with ``events``, ``features`` and, when ``use_model`` is True, ``results``. Pass ``match`` (from
    ``load_match``) to avoid loading the tracking again.
    """
    if match is None:
        match = load_match(match_id)
    events = build_events(match)
    features = all_features(match, events) if len(events) else pd.DataFrame(columns=["event_id"])
    output = dict(events=events, features=features)
    if use_model and len(events):
        output["results"] = score_events(events, features, model.load_model(model_path))
    if save:
        make_folders()
        events.to_csv(EVENTS_DIR / f"{match_id}.csv", index=False)
        features.to_csv(FEATURES_DIR / f"{match_id}.csv", index=False)
        if "results" in output:
            output["results"].to_csv(RESULTS_DIR / f"{match_id}.csv", index=False)
    return output


def run_many(match_ids=None, use_model=False, model_path=MODEL_PATH, skip_existing=False):
    """Run the event pipeline for several matches (all of them by default)."""
    for match_id in (match_ids or list_match_ids()):
        done = (EVENTS_DIR / f"{match_id}.csv").exists() and (FEATURES_DIR / f"{match_id}.csv").exists()
        if skip_existing and done and (not use_model or (RESULTS_DIR / f"{match_id}.csv").exists()):
            continue
        out = run_event_pipeline(match_id, use_model, model_path)
        print(f"match {match_id}: {len(out['events'])} hold-ups")


def read_datasets(folder, match_ids=None):
    """Read and stack the per-match csv files of one dataset (events, features or model results)."""
    files = sorted(folder.glob("*.csv"))
    if match_ids is not None:
        wanted = {f"{m}.csv" for m in match_ids}
        files = [f for f in files if f.name in wanted]
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


# ---------------------------------------------------------------- 2. training pipeline

def run_training_pipeline(model_path=MODEL_PATH, n_splits=10, repeats=5, save=True):
    """Train the retention model (and the expected-value model) on every match found in the events / features folders.

    Steps: calibrate expected pass completion out of fold; cross-validate the logistic regression, the boosted trees
    and their average (folds grouped by match); fit the final models on everything and save them. Also returns the
    honest out-of-fold model results for every training hold-up.
    """
    events = read_datasets(EVENTS_DIR)
    features = read_datasets(FEATURES_DIR)
    table = features.merge(events[["event_id", "match_id", "outcome", "retained", "epv_before", "value_added"]], on="event_id")

    # expected pass completion: physics value -> probability, calibrated against completed (received) vs intercepted
    completed = (table.outcome == "received").astype(int)
    table["xpass"] = model.calibrate_xpass_out_of_fold(table.xpass_raw, completed, table.match_id)
    platt = model.fit_platt(table.xpass_raw[table.xpass_raw.notna()], completed[table.xpass_raw.notna()])

    # expected retention: out-of-fold at first contact and at release
    labelled = table.retained.notna().to_numpy()
    data = table[labelled].reset_index(drop=True)
    y, groups = data.retained.astype(int).to_numpy(), data.match_id.to_numpy()
    contact_x, release_x = data[model.FEATURES], model.release_state(data)
    logit_contact, logit_release = model.cross_validated_predict(contact_x, y, groups, model.make_logit, release_x, n_splits, repeats)
    trees_contact, trees_release = model.cross_validated_predict(contact_x, y, groups, model.make_trees, release_x, n_splits, repeats)
    xr_contact = (logit_contact + trees_contact) / 2
    xr_release = (logit_release + trees_release) / 2

    # expected value added (EPV)
    has_value = data.value_added.notna().to_numpy()
    expected_value = pd.Series(float("nan"), index=data.index)
    expected_value[has_value] = model.cross_validated_value(data.loc[has_value, model.EPV_FEATURES], data.value_added[has_value],
                                                            data.match_id[has_value], n_splits, repeats)

    league_setup = float((xr_contact - xr_release).mean())
    results_labelled = model.build_results(data.event_id, data.xpass, xr_release, xr_contact, expected_value.to_numpy(),
                                           data[["retained", "value_added"]], league_setup)
    # hold-ups with no outcome (own shots) are not scored
    unscored = table[~labelled][["event_id", "xpass"]]
    results = pd.concat([results_labelled, unscored], ignore_index=True)

    metrics = {name: model.score(y, p) for name, p in
               (("logistic", logit_contact), ("boosted trees", trees_contact), ("average", xr_contact),
                ("base rate", pd.Series(y.mean(), index=range(len(y))).to_numpy()))}
    slope, intercept = model.calibration_slope(y, xr_contact)
    value_r2 = 1 - ((data.value_added[has_value] - expected_value[has_value]) ** 2).sum() \
        / ((data.value_added[has_value] - data.value_added[has_value].mean()) ** 2).sum()
    summary = dict(metrics=pd.DataFrame(metrics).T, calibration_slope=slope, calibration_intercept=intercept,
                   value_r2=float(value_r2), n_events=len(table), n_training=len(data), n_matches=int(data.match_id.nunique()),
                   base_rate=float(y.mean()), league_setup_mean=league_setup)

    final = model.fit_final_models(table, table.retained, table.value_added)
    final["league_setup_mean"] = league_setup
    final["xpass_platt"] = platt
    if save:
        make_folders()
        model.save_model(final, model_path)
        results.to_csv(TRAINING_DIR / "model_results_oof.csv", index=False)
        summary["metrics"].to_csv(TRAINING_DIR / "cv_metrics.csv")
    return dict(model=final, results=results, summary=summary, data=data, logit=logit_contact, trees=trees_contact,
                xr_contact=xr_contact, xr_release=xr_release, expected_value=expected_value, table=table)


# ---------------------------------------------------------------- 3. aggregation pipeline

SCORE_COLUMNS = ["aerial", "peak_height", "pass_distance", "con_n5", "con_oval_sum", "sup_n_xp60", "sup_n_lane_open"]


def build_scores(events, features, results):
    """One row per scored hold-up: who, outcome, model results and the features the scenarios use."""
    scores = events.merge(results, on="event_id").merge(features[["event_id"] + SCORE_COLUMNS], on="event_id")
    scores = scores[scores.retained.notna() & scores.roe_c.notna()].reset_index(drop=True)
    scores["key"] = scores.player + " | " + scores.team_name
    return scores


def run_aggregation_pipeline(results=None, events=None, features=None, save=True, draws=2000):
    """Aggregate hold-up model results into player stats.

    By default uses the out-of-fold results written by the training pipeline (so training matches are not scored by
    a model that saw them); pass ``results`` (for example stacked ``data/model_results`` files) to use another set.
    Returns a dict with ``player_stats``, ``scores`` (hold-up level, with z-scores), ``scenario_tags``,
    ``thresholds``, ``scenario_players`` and ``scenario_spread``.
    """
    events = read_datasets(EVENTS_DIR) if events is None else events
    features = read_datasets(FEATURES_DIR) if features is None else features
    results = pd.read_csv(TRAINING_DIR / "model_results_oof.csv") if results is None else results

    scores = aggregate.add_holdup_zscores(build_scores(events, features, results))
    tags, thresholds = aggregate.tag_scenarios(scores)
    minutes = aggregate.player_minutes(sorted(events.match_id.unique()), events)
    player_stats = aggregate.build_player_stats(scores, minutes, draws=draws)
    scenario_players, scenario_spread = aggregate.scenario_shrinkage(scores, tags, draws=draws)
    # tag columns on the hold-up table, for plots and tables
    scores = pd.concat([scores, tags.add_prefix("scenario_")], axis=1)
    if save:
        make_folders()
        player_stats.to_csv(PLAYERS_DIR / "player_stats.csv", index=False)
        scenario_players.to_csv(PLAYERS_DIR / "player_scenarios.csv", index=False)
        scores.to_csv(PLAYERS_DIR / "holdup_scores.csv", index=False)
        thresholds.to_csv(PLAYERS_DIR / "scenario_thresholds.csv")
        scenario_spread.to_csv(PLAYERS_DIR / "scenario_spread.csv")
    return dict(player_stats=player_stats, scores=scores, scenario_tags=tags, thresholds=thresholds,
                scenario_players=scenario_players, scenario_spread=scenario_spread)
