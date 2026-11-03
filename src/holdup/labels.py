"""What happened after each hold-up: the outcome (kept or lost) and the value (EPV) added.

Outcome. A hold-up succeeds if his team still has the ball 3 seconds (30 frames) after his first touch, whoever has it
by then; a foul won counts as a success. In order of precedence:

  defender_first - the defender won the ball before he touched it         -> lost
  own_shot       - his possession ends in a shot inside the window        (not scored: neither kept nor lost)
  foul_won       - his possession ends in a foul suffered, or a free kick / penalty for his team follows it
  lost           - his possession ends in a possession loss, clearance or unsuccessful / offside pass inside the
                   window; or an opponent possession starts inside the window; or the ball goes out to the opponent
  kept           - none of the above

His own end type only counts when it falls inside the window. ``retained`` is 1 for kept and foul_won, 0 for lost.

Value. SkillCorner's EPV (expected possession value, roughly the chance the possession ends in a goal) from his team's
point of view. before = EPV when he gets the ball. after = EPV at the start of the next possession (positive if his
team has it, negative if the opponent does) when that starts within 50 frames, otherwise EPV at the end of his own
possession. value_added = after - before.
"""
import numpy as np
import pandas as pd

WINDOW = 30         # frames after first contact (3 s)
MAX_GAP = 50        # frames: the next possession counts as 'action plus one' if it starts within this
LOST_END = {"possession_loss", "clearance"}
FOUL_AFTER = {"free_kick_for", "penalty_for"}
AGAINST_AFTER = {"throw_in_against", "goal_kick_against", "corner_against", "free_kick_against",
                 "penalty_against", "goal_against"}


def possession_table(match):
    return match["events"][match["events"].event_type == "player_possession"].sort_values("index").reset_index(drop=True)


def label_one(possessions, position, event, window=WINDOW):
    """Outcome of one hold-up: a dict with result, reason, hold_seconds and frames_to_loss."""
    contact = int(event.contact_frame)
    if event.outcome == "defender_first":
        return dict(result="lost", reason="defender_first", hold_seconds=np.nan, frames_to_loss=np.nan)
    row = possessions.loc[position[event.source_event_id]]
    stop = contact + window
    ends_in_window = row.frame_end <= stop
    later = possessions[(possessions.frame_start > contact) & (possessions.frame_start <= stop)
                        & (possessions.index != row.name)]
    opponent = later[later.team_id != event.team_id]
    hold = (min(row.frame_end, stop) - contact) / 10

    if ends_in_window and row.end_type == "shot":
        return dict(result="own_shot", reason="shot", hold_seconds=hold, frames_to_loss=np.nan)
    if ends_in_window and (row.end_type == "foul_suffered" or row.game_interruption_after in FOUL_AFTER):
        reason = row.end_type if row.end_type == "foul_suffered" else row.game_interruption_after
        return dict(result="foul_won", reason=reason, hold_seconds=hold, frames_to_loss=np.nan)
    if ends_in_window and (row.end_type in LOST_END or (row.end_type == "pass" and row.pass_outcome in ("unsuccessful", "offside"))):
        reason = row.end_type if row.end_type != "pass" else f"pass_{row.pass_outcome}"
        return dict(result="lost", reason=reason, hold_seconds=hold, frames_to_loss=row.frame_end - contact)
    if len(opponent):
        return dict(result="lost", reason="opponent_possession", hold_seconds=hold,
                    frames_to_loss=int(opponent.frame_start.min()) - contact)
    after = [(row.game_interruption_after, row.frame_end)] if ends_in_window else []
    after += list(zip(later.game_interruption_after, later.frame_end))
    against = [(a, f) for a, f in after if a in AGAINST_AFTER and f <= stop]
    if against:
        reason, frame = min(against, key=lambda t: t[1])
        return dict(result="lost", reason=reason, hold_seconds=hold, frames_to_loss=int(frame) - contact)
    return dict(result="kept", reason="no opponent possession in window", hold_seconds=hold, frames_to_loss=np.nan)


def label_outcomes(match, events):
    """Outcome columns aligned to ``events``: result, reason, hold_seconds, frames_to_loss, retained."""
    possessions = possession_table(match)
    position = dict(zip(possessions.event_id, possessions.index))
    rows = [label_one(possessions, position, event) for _, event in events.iterrows()]
    out = pd.DataFrame(rows, index=events.index, columns=["result", "reason", "hold_seconds", "frames_to_loss"])
    out["retained"] = out.result.map({"kept": 1.0, "foul_won": 1.0, "lost": 0.0})
    out["hold_seconds"] = pd.to_numeric(out.hold_seconds)
    out["frames_to_loss"] = pd.to_numeric(out.frames_to_loss)
    return out


def label_values(match, events):
    """EPV columns aligned to ``events``: end_type, epv_before, epv_after, after_source, value_added."""
    possessions = match["events"]
    possessions = possessions[possessions.event_type == "player_possession"]
    possessions = possessions.sort_values(["frame_start", "frame_end"]).reset_index(drop=True)
    position = {event_id: i for i, event_id in enumerate(possessions.event_id)}
    rows = []
    for _, event in events.iterrows():
        i = position[event.source_event_id]
        action = possessions.loc[i]
        following = possessions.loc[i + 1] if i + 1 < len(possessions) else None
        before, own_end = action.possession_epv_for_start, action.possession_epv_for_end
        gap = following.frame_start - action.frame_end if following is not None else np.nan
        if following is not None and gap <= MAX_GAP and pd.notna(following.possession_epv_for_start):
            sign = 1.0 if following.team_id == action.team_id else -1.0
            after, source = sign * following.possession_epv_for_start, "next possession"
        else:
            after, source = own_end, "own end"
        rows.append(dict(end_type=action.end_type, epv_before=before, epv_after=after, after_source=source,
                         value_added=after - before))
    return pd.DataFrame(rows, index=events.index)
