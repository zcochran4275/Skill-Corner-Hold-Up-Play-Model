"""Hold-up event detection.

A hold-up is a pass played to a forward who is posted on the opposition's back line, with his back to goal: the ball
comes from behind him, he is inside the box around the back line, and he has not gone beyond the line at his first
touch.

Candidates (passes to a forward):
  * received       - the forward is the receiver of a same-team pass
  * defender_first - a pass aimed at the forward is intercepted by an opponent who gets there first (a failed hold-up)

Gates (a candidate becomes an event only if it passes all four):
  1. linked       the pass and the first contact are at most 50 frames (5 s) apart
  2. from_behind  the ball travels towards the opposition goal, within 45 degrees of straight
  3. in_box       the striker is inside the back-line box at pass release OR at first contact
  4. not_behind   at first contact he is at most 1 m past the line

All positions are flipped so the striker's team attacks +x: the deepest defender has the largest x and a striker in
front of the back line has an x below the line height. Tracking is 10 frames per second.
"""
import numpy as np
import pandas as pd

from .data import attack_sign, team_names

FORWARDS = ("CF", "LF", "RF")
RESTARTS = {"goal_kick_reception": "goal_kick", "throw_in_reception": "throw_in",
            "free_kick_reception": "free_kick", "corner_reception": "corner"}
GATES = ["linked", "from_behind", "in_box", "not_behind"]

# The final settings (metres unless stated)
SETTINGS = dict(
    max_gap=50,            # frames between pass release and first contact
    max_angle=45.0,        # degrees: ball direction must be within this of straight at goal
    arrival_radius=5.0,    # a pass that was intercepted counts only if the ball got this close to the forward
    join_gap=5.0,          # back line: a defender joins if within this x-distance of one already in the line
    max_span=15.0,         # back line: members stay within this x-distance of the seed defender
    max_members=4,         # back line: at most this many defenders
    depth_front=10.0,      # box reaches this far in front of the line height
    depth_behind=10.0,     # ... and this far behind it
    small_line_max=2,      # a line of this many defenders or fewer ...
    small_margin=5.0,      # ... gets this much room either side of its defenders (the box is otherwise too narrow)
    behind_tol=1.0,        # allowed distance past the line at first contact
)


# ---------------------------------------------------------------- candidates

def restart_type(start_type):
    """Restart type of the passer's possession, otherwise open play."""
    return start_type.map(RESTARTS).fillna("open_play")


def find_candidates(match):
    """Every pass to a forward: received, or intercepted with the defender first."""
    events = match["events"]
    possessions = events[events.event_type == "player_possession"].sort_values("index").reset_index(drop=True)
    previous = possessions.shift(1)
    following = possessions.shift(-1)
    max_gap = SETTINGS["max_gap"]

    # received passes: the forward's possession starts with a pass reception
    rec = possessions[(possessions.start_type == "pass_reception") & possessions.player_position.isin(FORWARDS)]
    prev = previous.loc[rec.index]
    gap = rec.frame_start - prev.frame_end
    received = pd.DataFrame(dict(
        source_event_id=rec.event_id, player_id=rec.player_id, player=rec.player_name, team_id=rec.team_id,
        position=rec.player_position, release_frame=prev.frame_end, contact_frame=rec.frame_start, gap=gap,
        passer_id=prev.player_id, origin=restart_type(prev.start_type), outcome="received",
        linked=(prev.team_id == rec.team_id) & (prev.end_type == "pass") & gap.between(0, max_gap)))

    # failed passes aimed at a forward and intercepted by the opposition
    failed_pass = possessions[(possessions.end_type == "pass") & (possessions.pass_outcome == "unsuccessful")
                              & possessions.player_targeted_position.isin(FORWARDS)]
    nxt = following.loc[failed_pass.index]
    intercepted = (nxt.team_id != failed_pass.team_id) & (nxt.start_type == "pass_interception") \
        & (nxt.frame_start - failed_pass.frame_end).between(0, max_gap)
    failed_pass, nxt = failed_pass[intercepted], nxt[intercepted]
    failed = pd.DataFrame(dict(
        source_event_id=failed_pass.event_id, player_id=failed_pass.player_targeted_id.astype(int),
        player=failed_pass.player_targeted_name, team_id=failed_pass.team_id, position=failed_pass.player_targeted_position,
        release_frame=failed_pass.frame_end, contact_frame=nxt.frame_start,   # refined later to the ball's closest approach
        gap=nxt.frame_start - failed_pass.frame_end, passer_id=failed_pass.player_id,
        origin=restart_type(failed_pass.start_type), outcome="defender_first", linked=True))

    candidates = pd.concat([received, failed]).reset_index(drop=True)
    candidates.insert(0, "match_id", match["match_id"])
    return candidates


# ---------------------------------------------------------------- frame snapshots

def frame_snapshot(match, frame, team_id, player_id):
    """Striker, ball and opposing outfield players at one frame, flipped so the striker's team attacks +x.

    Returns None if the striker is not tracked at that frame.
    """
    tracking = match["tracking"]
    if frame not in tracking.index:
        return None
    rows = tracking.loc[[frame]]
    me = rows[rows.player_id == player_id]
    if me.empty or me.x.isna().any():
        return None
    sign = attack_sign(match, team_id, int(rows.period.iloc[0]))
    opponents = rows[(rows.team_id != team_id) & ~rows.player_id.isin(match["goalkeepers"]) & rows.x.notna()]
    ball = match["frames"].loc[frame]
    return dict(striker_x=float(me.x.iloc[0]) * sign, striker_y=float(me.y.iloc[0]) * sign,
                ball_x=ball.ball_x * sign, ball_y=ball.ball_y * sign,
                opp_ids=opponents.player_id.to_numpy(), opp_x=opponents.x.to_numpy() * sign,
                opp_y=opponents.y.to_numpy() * sign)


def closest_approach(match, player_id, first_frame, last_frame):
    """Frame between first_frame and last_frame where the ball is nearest the player, and that distance."""
    window = match["tracking"].loc[first_frame:last_frame]
    window = window[window.player_id == player_id]
    if window.empty:
        return None, np.nan
    ball = match["frames"].reindex(window.frame)
    distance = np.hypot(window.x.to_numpy() - ball.ball_x.to_numpy(), window.y.to_numpy() - ball.ball_y.to_numpy())
    if np.isnan(distance).all():
        return None, np.nan
    best = int(np.nanargmin(distance))
    return int(window.frame.iloc[best]), float(distance[best])


# ---------------------------------------------------------------- back line and box

def find_back_line(defender_x, defender_y):
    """The opposition back line: a dict with its members, height and y extent (None if fewer than 2 defenders).

    1. The seed is the second-deepest outfield defender, so one covering defender cannot set the line alone.
    2. Add the defender nearest the seed (in x) that is within ``join_gap`` of someone already in the line and
       within ``max_span`` of the seed. Repeat until nobody qualifies or the line has ``max_members`` defenders.
    The line height is the median x of its members.
    """
    x = np.asarray(defender_x, dtype=float)
    y = np.asarray(defender_y, dtype=float)
    valid = np.flatnonzero(~np.isnan(x) & ~np.isnan(y))
    if len(valid) < 2:
        return None
    deepest_first = valid[np.argsort(-x[valid])]
    seed = deepest_first[1]
    members = [seed]
    while len(members) < SETTINGS["max_members"]:
        pool = []
        for i in deepest_first:
            if i in members or abs(x[i] - x[seed]) > SETTINGS["max_span"]:
                continue
            if any(abs(x[i] - x[j]) <= SETTINGS["join_gap"] for j in members):
                pool.append(i)
        if not pool:
            break
        members.append(min(pool, key=lambda i: abs(x[i] - x[seed])))
    members = np.array([i for i in deepest_first if i in members])
    return dict(members=members, height=float(np.median(x[members])), n=len(members),
                y_low=float(y[members].min()), y_high=float(y[members].max()),
                y_mid=float(y[members].mean()), span=float(x[members].max() - x[members].min()))


def box_edges(line):
    """Box around a back line: (x_low, x_high, y_low, y_high).

    Depth: 10 m in front of the line height to 10 m behind it. Width: the y extent of the line's own defenders; a line
    of one or two defenders has almost no width, so it gets 5 m either side of them.
    """
    y_low, y_high = line["y_low"], line["y_high"]
    if line["n"] <= SETTINGS["small_line_max"]:
        y_low, y_high = y_low - SETTINGS["small_margin"], y_high + SETTINGS["small_margin"]
    return line["height"] - SETTINGS["depth_front"], line["height"] + SETTINGS["depth_behind"], y_low, y_high


def inside_box(striker_x, striker_y, line):
    x_low, x_high, y_low, y_high = box_edges(line)
    return bool(x_low <= striker_x <= x_high and y_low <= striker_y <= y_high)


# ---------------------------------------------------------------- detection

def check_candidate(match, candidate):
    """Measurements and the four gate flags for one candidate. Returns a dict."""
    row = candidate.drop(["linked"]).to_dict()
    linked = bool(candidate.linked)
    contact = int(candidate.contact_frame)
    arrival_distance = np.nan
    if linked and candidate.outcome == "defender_first":
        # the contact frame is where the ball comes closest to the forward; far away means he was never in the play
        frame, arrival_distance = closest_approach(match, candidate.player_id, int(candidate.release_frame), contact)
        if frame is None or arrival_distance > SETTINGS["arrival_radius"]:
            linked = False
        else:
            contact = frame
    row["contact_frame"] = contact
    flags = dict(from_behind=False, in_box=False, not_behind=False, in_box_release=False, in_box_contact=False)
    if linked:
        at_release = frame_snapshot(match, int(candidate.release_frame), candidate.team_id, candidate.player_id)
        at_contact = frame_snapshot(match, contact, candidate.team_id, candidate.player_id)
        if at_release is not None and at_contact is not None:
            line_release = find_back_line(at_release["opp_x"], at_release["opp_y"])
            line_contact = find_back_line(at_contact["opp_x"], at_contact["opp_y"])
            if line_release is not None and line_contact is not None:
                angle = float(np.degrees(np.arctan2(at_contact["ball_y"] - at_release["ball_y"],
                                                    at_contact["ball_x"] - at_release["ball_x"])))
                row.update(
                    striker_x_release=at_release["striker_x"], striker_y_release=at_release["striker_y"],
                    striker_x_contact=at_contact["striker_x"], striker_y_contact=at_contact["striker_y"],
                    line_x_release=line_release["height"], line_x_contact=line_contact["height"],
                    line_dist_release=at_release["striker_x"] - line_release["height"],
                    past_line_contact=at_contact["striker_x"] - line_contact["height"],
                    n_line_release=line_release["n"], n_line_contact=line_contact["n"],
                    box_y_low_release=line_release["y_low"], box_y_high_release=line_release["y_high"],
                    box_y_low_contact=line_contact["y_low"], box_y_high_contact=line_contact["y_high"],
                    ball_angle=angle, ball_x_release=at_release["ball_x"], ball_y_release=at_release["ball_y"],
                    ball_x_contact=at_contact["ball_x"], ball_y_contact=at_contact["ball_y"],
                )
                flags["from_behind"] = abs(angle) <= SETTINGS["max_angle"]
                flags["in_box_release"] = inside_box(at_release["striker_x"], at_release["striker_y"], line_release)
                flags["in_box_contact"] = inside_box(at_contact["striker_x"], at_contact["striker_y"], line_contact)
                flags["in_box"] = flags["in_box_release"] or flags["in_box_contact"]
                flags["not_behind"] = row["past_line_contact"] <= SETTINGS["behind_tol"]
    return {**row, "arrival_distance": arrival_distance, "linked": linked, **flags}


def detect_candidates(match):
    """One row per candidate with its measurements and gate flags (before the gates are applied)."""
    rows = [check_candidate(match, c) for _, c in find_candidates(match).iterrows()]
    return pd.DataFrame(rows)


def gate_counts(candidates):
    """How many candidates survive each gate in turn (for the funnel)."""
    keep = pd.Series(True, index=candidates.index)
    counts = {"candidates": len(candidates)}
    for gate in GATES:
        keep &= candidates[gate].fillna(False).astype(bool)
        counts[gate] = int(keep.sum())
    return pd.Series(counts)


def detect_events(match):
    """The hold-up events of one match: candidates that pass every gate, with an ``event_id``.

    ``event_id`` is ``<match_id>_<nnn>``, numbered in order of first contact. It is the key that joins the event,
    feature and model-results datasets. ``source_event_id`` is SkillCorner's own id of the possession.
    """
    candidates = detect_candidates(match)
    passed = candidates[GATES].fillna(False).astype(bool).all(axis=1)
    events = candidates[passed].sort_values(["contact_frame", "release_frame"]).reset_index(drop=True)
    events.insert(0, "event_id", [f"{match['match_id']}_{i + 1:03d}" for i in range(len(events))])
    names = team_names(match)
    events["team_name"] = events.team_id.map(names)
    return events
