"""Load every match and sanity-check tracking normalisation against events."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from holdup.data import attack_sign, list_match_ids, load_match

for match_id in list_match_ids():
    match = load_match(match_id)
    events = match["events"]
    possessions = events[(events.event_type == "player_possession") & events.frame_start.notna()]
    # attacking_side in events: is it consistent with the goalkeeper-based sign?
    bad = total = 0
    for team_id, team_rows in possessions.groupby("team_id"):
        for period, rows in team_rows.groupby("period"):
            if (team_id, period) not in match["gk_x"].index:
                continue
            left_to_right = attack_sign(match, team_id, period) == 1
            total += 1
            bad += (rows.attacking_side.iloc[0] == "left_to_right") != left_to_right
    unmatched = match["tracking"].team_id.isna().sum()
    print(f"{match_id}: frames={len(match['frames'])} rows={len(match['tracking'])} "
          f"pitch=({match['pitch_length']}, {match['pitch_width']}) side-mismatch={bad}/{total} untracked-team-rows={unmatched}")
