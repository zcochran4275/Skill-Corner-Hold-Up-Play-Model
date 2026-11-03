"""Where every file lives. Notebooks and pipelines import these instead of typing paths."""
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
DATA = PROJECT / "data"

RAW_DIR = DATA / "raw"                    # SkillCorner downloads, one folder per match
EVENTS_DIR = DATA / "events"              # event detection dataset, one csv per match
FEATURES_DIR = DATA / "features"          # feature dataset, one csv per match
RESULTS_DIR = DATA / "model_results"      # model results dataset, one csv per match
MODEL_DIR = DATA / "models"               # saved model
TRAINING_DIR = DATA / "training"          # cross-validation output
PLAYERS_DIR = DATA / "players"            # player stats

MODEL_PATH = MODEL_DIR / "holdup_model.joblib"


def make_folders():
    """Create the output folders if they do not exist yet."""
    for folder in (EVENTS_DIR, FEATURES_DIR, RESULTS_DIR, MODEL_DIR, TRAINING_DIR, PLAYERS_DIR):
        folder.mkdir(parents=True, exist_ok=True)
