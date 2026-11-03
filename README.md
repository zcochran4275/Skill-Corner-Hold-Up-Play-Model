# Hold-Up Play Model

Scores how well a forward holds the ball up with his back to goal, adjusted for how hard each situation was, and splits his retention into **set-up added** (movement before the pass) and **duel added** (winning the contact). Built on SkillCorner open tracking and event data.

## Documentation

| File | Contents |
| --- | --- |
| [docs/01_build_spec.md](docs/01_build_spec.md) | Full design spec: concepts, event definition, features, outcome, xR model, value added, outputs, visuals, pilot results |
| [docs/02_component_choices.md](docs/02_component_choices.md) | Decisions on data, pressure, EPV, support options and the hold-up definition (overrides the spec) |
| [docs/03_roadmap.md](docs/03_roadmap.md) | Build steps in order, as a checklist |
| [docs/04_data_notes.md](docs/04_data_notes.md) | What the open data contains, column map, gotchas |

## Status

The method is finished and packaged as three pipelines and three notebooks. The 16 exploration notebooks, the band detector and the box variants are kept in `archive/` (git-ignored) for reference.

| Notebook | What it covers |
| --- | --- |
| [01_event_detection](notebooks/01_event_detection.ipynb) | how a hold-up is detected (candidates, back line, box, gates, outcome and EPV labels) and the method behind every feature |
| [02_model_training](notebooks/02_model_training.ipynb) | training the retention model (xR), cross-validation and evaluation, set-up / duel split, expected EPV, the saved model |
| [03_player_evaluation](notebooks/03_player_evaluation.ipynb) | the aggregation pipeline: shrinkage, z-scores, scenarios, set-up vs duel and RoE vs EPV scatterplots |

At this sample size (about 535 hold-ups, 20 matches) striker-level RoE, set-up and duel differences are within noise; the service a striker receives is the stable signal.

## Pipelines (`src/holdup/pipelines.py`)

```python
from holdup.pipelines import run_event_pipeline, run_many, run_training_pipeline, run_aggregation_pipeline

run_event_pipeline(1874553, use_model=False)   # detect + features for one match -> data/events, data/features
run_many()                                      # all matches (about 25 s each)
run_training_pipeline()                         # trains and saves data/models/holdup_model.joblib
run_event_pipeline(1874553, use_model=True)     # also writes data/model_results
run_aggregation_pipeline()                      # data/players/player_stats.csv and friends
```

All datasets share the key `event_id` (`<match_id>_<nnn>`). The code is plain functions, no classes: `data.py` (loading), `detection.py`, `labels.py`, `features.py`, `model.py`, `aggregate.py`, `plots.py`, `paths.py`.

```
data/
  raw/            SkillCorner downloads
  events/         event detection dataset, one csv per match
  features/       feature dataset, one csv per match
  model_results/  model results dataset (model on)
  models/         saved model
  training/       out-of-fold results and cross-validation metrics
  players/        player_stats.csv, player_scenarios.csv, holdup_scores.csv
  archive/        the old per-variant processed folders
```

## Data

SkillCorner open data (A-League 2024/25): https://github.com/SkillCorner/opendata. Raw data goes in `data/raw/` and is not committed. Run `python scripts/download_data.py` (add `--no-tracking` to skip the ~1.8 GB tracking files); `python scripts/inspect_data.py` summarises it. See [docs/04_data_notes.md](docs/04_data_notes.md).
