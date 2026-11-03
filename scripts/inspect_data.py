"""Summarise the downloaded SkillCorner dynamic events and phases of play."""
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

ev = pd.concat(
    (pd.read_csv(p, low_memory=False) for p in sorted(RAW.glob("*/*_dynamic_events.csv"))),
    ignore_index=True,
)
ph = pd.concat(
    (pd.read_csv(p, low_memory=False).assign(match_id=int(p.parent.name)) for p in sorted(RAW.glob("*/*_phases_of_play.csv"))),
    ignore_index=True,
)
print("matches:", ev.match_id.nunique(), "| event rows:", len(ev), "| columns:", ev.shape[1])
print("\nevent_type counts:\n", ev.event_type.value_counts().to_string())

pp = ev[ev.event_type == "player_possession"]
print("\nstart_type:\n", pp.start_type.value_counts(dropna=False).to_string())
print("\nend_type:\n", pp.end_type.value_counts(dropna=False).to_string())
print("\nplayer_position (reception starts):\n",
      pp[pp.start_type == "pass_reception"].player_position.value_counts().to_string())

recv = pp[pp.start_type == "pass_reception"]
fwd = recv[recv.player_position.isin(["CF", "LF", "RF"])]
print("\nforward receptions:", len(fwd), "| CF only:", (recv.player_position == "CF").sum())
print("attacking-third starts (forwards):", (fwd.third_start == "attacking_third").sum())
print("open play (no interruption before):", fwd.game_interruption_before.isna().sum())
print("start matched:", fwd.is_player_possession_start_matched.sum(),
      "| previous pass matched:", fwd.is_previous_pass_matched.sum())

groups = {
    "EPV": "epv",
    "pressure/difficulty labels": "pressure|difficulty|space_constraint|time_to_impact|passing_option_ease",
    "last line": "last_defensive_line|delta_to_last",
    "separation": "separation",
    "phase": "phase",
}
for label, pat in groups.items():
    cols = [c for c in ev.columns if pd.Series(c).str.contains(pat).item()]
    print(f"\n{label} ({len(cols)}):", ", ".join(cols))
print("\nhigh_pass in:", "high_pass" in ev.columns, "| is_header in:", "is_header" in ev.columns)
print("\nphases columns:", ", ".join(ph.columns))
