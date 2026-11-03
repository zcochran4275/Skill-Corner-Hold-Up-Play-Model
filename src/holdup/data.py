"""Load one SkillCorner open-data match.

A match is a plain dictionary:

    match["match_id"]   the id
    match["meta"]       the match json (teams, players, pitch size)
    match["events"]     dynamic events table
    match["players"]    one row per player: player_id, team_id, role, name, is_gk
    match["frames"]     one row per frame (index = frame): period, ball_x, ball_y, ball_z, ball_detected
    match["tracking"]   one row per player per frame (index = frame): period, player_id, team_id, x, y
    match["goalkeepers"] set of goalkeeper player ids
    match["gk_x"]       average goalkeeper x per (team, period); tells which way a team attacks

Tracking coordinates are raw (pitch centre, metres, sides swap at half-time). Use ``attack_sign`` to flip a team's
coordinates so that it always attacks towards +x.
"""
import json

import pandas as pd

from .paths import RAW_DIR


def read_players(meta):
    rows = []
    for p in meta["players"]:
        rows.append(dict(player_id=p["id"], team_id=p["team_id"], role=p["player_role"]["acronym"],
                         number=p["number"], name=p["short_name"]))
    players = pd.DataFrame(rows)
    players["is_gk"] = players.role == "GK"
    return players


def read_tracking(path, team_of):
    """Read the tracking jsonl file: one line per frame."""
    frame_rows = []
    player_rows = []
    with open(path) as f:
        for line in f:
            d = json.loads(line)
            if d["period"] is None:
                continue                                  # frames outside play carry no data
            ball = d["ball_data"]
            frame_rows.append((d["frame"], d["period"], ball["x"], ball["y"], ball["z"], ball["is_detected"]))
            for pl in d["player_data"]:
                player_rows.append((d["frame"], d["period"], pl["player_id"], team_of.get(pl["player_id"]), pl["x"], pl["y"]))
    frames = pd.DataFrame(frame_rows, columns=["frame", "period", "ball_x", "ball_y", "ball_z", "ball_detected"])
    tracking = pd.DataFrame(player_rows, columns=["frame", "period", "player_id", "team_id", "x", "y"])
    # index by frame (sorted) so that looking up a frame or a range of frames is fast; keep frame as a column too
    frames = frames.set_index("frame", drop=False).sort_index()
    tracking = tracking.set_index("frame", drop=False).sort_index()
    return frames, tracking


def load_match(match_id, with_tracking=True):
    """Load a match. With ``with_tracking=False`` only meta, events and players are read (fast)."""
    folder = RAW_DIR / str(match_id)
    meta = json.loads((folder / f"{match_id}_match.json").read_text(encoding="utf-8"))
    events = pd.read_csv(folder / f"{match_id}_dynamic_events.csv", low_memory=False)
    players = read_players(meta)
    match = dict(match_id=int(match_id), meta=meta, events=events, players=players,
                 goalkeepers=set(players.loc[players.is_gk, "player_id"]),
                 pitch_length=meta["pitch_length"], pitch_width=meta["pitch_width"],
                 frames=None, tracking=None, gk_x=None)
    if with_tracking:
        team_of = dict(zip(players.player_id, players.team_id))
        frames, tracking = read_tracking(folder / f"{match_id}_tracking_extrapolated.jsonl", team_of)
        gk_tracking = tracking[tracking.player_id.isin(match["goalkeepers"])]
        match["frames"] = frames
        match["tracking"] = tracking
        match["gk_x"] = gk_tracking.groupby(["team_id", "period"])["x"].mean()
    return match


def attack_sign(match, team_id, period):
    """+1 if the team already attacks towards +x in raw coordinates, -1 if its coordinates must be flipped."""
    goalkeeper_x = match["gk_x"].loc[(team_id, period)]
    return 1 if goalkeeper_x < 0 else -1


def team_names(match):
    """{team_id: short name}"""
    meta = match["meta"]
    return {meta["home_team"]["id"]: meta["home_team"]["short_name"],
            meta["away_team"]["id"]: meta["away_team"]["short_name"]}


def list_match_ids():
    return sorted(int(p.name) for p in RAW_DIR.iterdir() if p.is_dir())
