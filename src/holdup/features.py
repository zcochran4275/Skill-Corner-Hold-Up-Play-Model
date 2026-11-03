"""Features for each hold-up event. Every function takes one match and that match's events and returns a table of
new columns with the same index as ``events``.

All positions are flipped so the striker's team attacks +x. Distances are in metres, speeds in m/s, 10 frames per second.

  pass_features        how hard the ball played to the striker was (aerial, peak height, flight time, distance, origin)
  pressure_features    defenders around the striker at release (rel_) and first contact (con_)
  support_features     teammates he could lay the ball off to, at first contact (sup_) or release (suprel_)
  prereceipt_features  his own movement while the ball is in the air, and the height of the back line
  xpass_features       how likely the pass was to get through the defence (physics model, uncalibrated)
"""
import numpy as np
import pandas as pd

from .data import attack_sign
from .detection import frame_snapshot

FPS = 10
AERIAL_HEIGHT = 2.0      # m: a ball that peaks higher than this is aerial (also aerial if the event is flagged a high pass)


# ---------------------------------------------------------------- velocities and opponent snapshots

def player_velocities(tracking, frame, half_window, sign):
    """Velocity (m/s, attacking +x) of every player from the positions half_window frames before and after."""
    try:
        before = tracking.loc[[frame - half_window]].set_index("player_id")
        after = tracking.loc[[frame + half_window]].set_index("player_id")
    except KeyError:
        return pd.DataFrame({"vx": pd.Series(dtype=float), "vy": pd.Series(dtype=float)})
    ids = before.index.intersection(after.index)
    seconds = 2 * half_window / FPS
    return pd.DataFrame({"vx": (after.x[ids] - before.x[ids]) / seconds * sign,
                         "vy": (after.y[ids] - before.y[ids]) / seconds * sign})


def pack_players(rows, velocities, sign):
    ids = rows.player_id.to_numpy()
    v = velocities.reindex(ids).fillna(0.0)
    return dict(id=ids, x=rows.x.to_numpy() * sign, y=rows.y.to_numpy() * sign, vx=v.vx.to_numpy(), vy=v.vy.to_numpy())


def moving_snapshot(match, frame, team_id, player_id, half_window=2):
    """Striker, his teammates (no goalkeeper) and all opponents (goalkeeper included) with position and velocity."""
    tracking = match["tracking"]
    if frame not in tracking.index:
        return None
    rows = tracking.loc[[frame]]
    me = rows[rows.player_id == player_id]
    if me.empty or me.x.isna().any():
        return None
    sign = attack_sign(match, team_id, int(rows.period.iloc[0]))
    v = player_velocities(tracking, frame, half_window, sign)
    mates = rows[(rows.team_id == team_id) & (rows.player_id != player_id)
                 & ~rows.player_id.isin(match["goalkeepers"]) & rows.x.notna()]
    opponents = rows[(rows.team_id != team_id) & rows.x.notna()]
    return dict(striker_x=float(me.x.iloc[0]) * sign, striker_y=float(me.y.iloc[0]) * sign,
                mates=pack_players(mates, v, sign), opponents=pack_players(opponents, v, sign))


# ---------------------------------------------------------------- pass features

def pass_features(match, events):
    """aerial, peak_height, flight_s, pass_distance, origin_x for the pass into each hold-up."""
    columns = ["aerial", "peak_height", "flight_s", "pass_distance", "origin_x"]
    out = pd.DataFrame(np.nan, index=events.index, columns=columns)
    possessions = match["events"][match["events"].event_type == "player_possession"]
    high_pass_flag = {(int(f), int(p)): hp for f, p, hp in zip(possessions.frame_end, possessions.player_id, possessions.high_pass)}
    for idx, e in events.iterrows():
        release, contact = int(e.release_frame), int(e.contact_frame)
        flight = match["frames"].loc[release:contact]
        distance = float(np.hypot(e.striker_x_contact - e.ball_x_release, e.striker_y_contact - e.ball_y_release))
        peak = float(flight.ball_z.max()) if flight.ball_z.notna().any() else np.nan
        flag = high_pass_flag.get((release, int(e.passer_id)))
        flagged = flag is True or flag == "True"
        aerial = 1.0 if (flagged or (not np.isnan(peak) and peak > AERIAL_HEIGHT)) else 0.0
        out.loc[idx] = [aerial, peak, (contact - release) / FPS, distance, e.ball_x_release]
    return out


# ---------------------------------------------------------------- pressure

OVAL = dict(front=9.0, back=3.0, side=6.0, q=1.75)    # oval reach (m) towards goal, away from goal, sideways; fall-off


def pressure_at(snapshot):
    """n5: defenders within 5 m. oval_sum: sum over defenders of (1 - scaled distance) ** q inside an oval around him
    (long reach on the goal side, short behind, medium sideways)."""
    dx = snapshot["opp_x"] - snapshot["striker_x"]
    dy = snapshot["opp_y"] - snapshot["striker_y"]
    n5 = int((np.hypot(dx, dy) <= 5).sum())
    reach_x = np.where(dx >= 0, OVAL["front"], OVAL["back"])
    scaled = np.hypot(dx / reach_x, dy / OVAL["side"])
    weight = (1 - np.minimum(scaled, 1.0)) ** OVAL["q"]
    return n5, float(weight.sum())


def pressure_features(match, events):
    """rel_n5, rel_oval_sum (at pass release) and con_n5, con_oval_sum (at first contact)."""
    out = pd.DataFrame(np.nan, index=events.index, columns=["rel_n5", "rel_oval_sum", "con_n5", "con_oval_sum"])
    for idx, e in events.iterrows():
        for prefix, frame in (("rel", int(e.release_frame)), ("con", int(e.contact_frame))):
            snapshot = frame_snapshot(match, frame, e.team_id, e.player_id)
            if snapshot is None or len(snapshot["opp_x"]) == 0:
                continue
            out.loc[idx, f"{prefix}_n5"], out.loc[idx, f"{prefix}_oval_sum"] = pressure_at(snapshot)
    return out


# ---------------------------------------------------------------- support

SUPPORT = dict(
    radius=30.0,        # teammates within this distance count as options
    lane_clear=2.0,     # an opponent within this of the pass line blocks it
    marker_dist=3.0,    # the teammate's nearest opponent must be further than this for the lane to be open
    pass_speed=14.0,    # m/s ball speed of a lay-off
    reaction=0.5,       # s a defender needs before reacting
    top_speed=7.0,      # m/s defender top speed
    sigma=0.4,          # s spread of the interception margin
    step=1.0,           # m spacing of the path points checked
    good_pass=0.6,      # a teammate is a real option if the pass would complete at least this often
)


def interception_chance(t_ball, path_x, path_y, opp_x, opp_y, opp_vx, opp_vy):
    """Chance a ball that reaches path point k at time t_ball[k] gets past every opponent.

    A defender keeps moving as he is for ``reaction`` seconds, then runs straight at a path point at top speed. He
    beats the ball to that point with a logistic probability of (ball time - his time). The pass completes if no
    defender gets there: product over defenders of (1 - best chance along the path).
    """
    if len(opp_x) == 0:
        return 1.0
    reach_x, reach_y = opp_x + opp_vx * SUPPORT["reaction"], opp_y + opp_vy * SUPPORT["reaction"]
    defender_time = SUPPORT["reaction"] + np.hypot(path_x[:, None] - reach_x[None, :],
                                                   path_y[:, None] - reach_y[None, :]) / SUPPORT["top_speed"]
    scale = SUPPORT["sigma"] * np.sqrt(3) / np.pi
    beats_ball = 1.0 / (1.0 + np.exp(-(t_ball[:, None] - defender_time) / scale))
    return float(np.prod(1.0 - beats_ball.max(axis=0)))


def straight_pass_completion(sx, sy, tx, ty, opponents):
    """Chance a ball played in a straight line from (sx, sy) to (tx, ty) gets past the opponents."""
    distance = float(np.hypot(tx - sx, ty - sy))
    n_points = max(2, int(distance / SUPPORT["step"]) + 1)
    u = np.linspace(0, 1, n_points)[1:]                               # path points, start excluded
    return interception_chance(u * distance / SUPPORT["pass_speed"], sx + u * (tx - sx), sy + u * (ty - sy),
                               opponents["x"], opponents["y"], opponents["vx"], opponents["vy"])


def distance_to_segment(px, py, ax, ay, bx, by):
    """Distance from points (px, py) to the segment from a to b."""
    abx, aby = bx - ax, by - ay
    length2 = abx ** 2 + aby ** 2
    t = np.clip(((px - ax) * abx + (py - ay) * aby) / length2, 0, 1) if length2 > 0 else np.zeros_like(px)
    return np.hypot(px - (ax + t * abx), py - (ay + t * aby))


def support_counts(snapshot):
    """n_xp60: teammates he could pass to with at least a 60% completion chance. n_lane_open: teammates with a clear
    lane (no opponent near the pass line and none close to the teammate)."""
    mates, opponents = snapshot["mates"], snapshot["opponents"]
    sx, sy = snapshot["striker_x"], snapshot["striker_y"]
    n_good, n_open = 0, 0
    for j in range(len(mates["x"])):
        tx, ty = mates["x"][j], mates["y"][j]
        if np.hypot(tx - sx, ty - sy) > SUPPORT["radius"]:
            continue
        if len(opponents["x"]):
            near_line = distance_to_segment(opponents["x"], opponents["y"], sx, sy, tx, ty).min()
            marker = np.hypot(opponents["x"] - tx, opponents["y"] - ty).min()
            n_open += int(near_line > SUPPORT["lane_clear"] and marker > SUPPORT["marker_dist"])
        else:
            n_open += 1
        n_good += int(straight_pass_completion(sx, sy, tx, ty, opponents) >= SUPPORT["good_pass"])
    return n_good, n_open


def support_features(match, events, frame_col="contact_frame", prefix="sup_"):
    """sup_n_xp60 and sup_n_lane_open at first contact; with frame_col='release_frame', prefix='suprel_' at release."""
    out = pd.DataFrame(np.nan, index=events.index, columns=[f"{prefix}n_xp60", f"{prefix}n_lane_open"])
    for idx, e in events.iterrows():
        snapshot = moving_snapshot(match, int(e[frame_col]), e.team_id, e.player_id)
        if snapshot is not None:
            out.loc[idx] = support_counts(snapshot)
    return out


# ---------------------------------------------------------------- the striker's own movement

SPEED_WINDOW = 5      # frames (0.5 s) over which speed is measured


def speeds_before_contact(match, e):
    """His speed over the last 0.5 s at pass release and at first contact (m/s). NaN if tracking is incomplete."""
    release, contact = int(e.release_frame), int(e.contact_frame)
    rows = match["tracking"].loc[release - SPEED_WINDOW:contact]
    if rows.empty:
        return np.nan, np.nan
    sign = attack_sign(match, e.team_id, int(rows.period.iloc[-1]))
    me = rows[rows.player_id == e.player_id].set_index("frame")[["x", "y"]].astype(float) * sign
    opponents = rows[(rows.team_id != e.team_id) & ~rows.player_id.isin(match["goalkeepers"]) & rows.x.notna()]
    if me.empty or opponents.empty or release not in me.index or contact not in me.index:
        return np.nan, np.nan
    # the old definition also needed an opponent to be visible at both moments; keep it so results do not change
    seen = opponents[(opponents.frame == release) | (opponents.frame == contact)]
    mine = me.reindex(seen.frame)
    ok = ~np.isnan(mine.x.to_numpy()) & ~np.isnan(mine.y.to_numpy())
    if not (set(seen.frame[ok]) >= {release, contact}):
        return np.nan, np.nan
    full = me.reindex(range(release - SPEED_WINDOW, contact + 1))
    vx = full.x.diff(SPEED_WINDOW) / (SPEED_WINDOW / FPS)
    vy = full.y.diff(SPEED_WINDOW) / (SPEED_WINDOW / FPS)
    speed = np.hypot(vx, vy)
    return float(speed.get(release, np.nan)), float(speed.get(contact, np.nan))


def prereceipt_features(match, events):
    """pre_speed_rel, pre_speed_con (his speed) and pre_line_height (back line height measured from the goal line)."""
    out = pd.DataFrame(np.nan, index=events.index, columns=["pre_speed_rel", "pre_speed_con", "pre_line_height"])
    half_length = match["pitch_length"] / 2
    for idx, e in events.iterrows():
        out.loc[idx, ["pre_speed_rel", "pre_speed_con"]] = speeds_before_contact(match, e)
        out.loc[idx, "pre_line_height"] = half_length - e.line_x_release
    return out


# ---------------------------------------------------------------- expected pass completion

XPASS = dict(reaction=0.5, top_speed=7.0, sigma=0.4, max_height=2.0)


def trajectory_completion(t, px, py, pz, opp_x, opp_y, opp_vx, opp_vy):
    """Chance the ball, moving through points (px, py, pz) at times t, gets past opponents at (opp_x, opp_y).

    Same interception model as for the support options, but along the ball's actual path. A defender can only play the
    ball where it is low enough (at most 2 m); the last point of the path (where the ball is first contested) always
    counts, so a lofted ball only has to beat the defenders near where it starts and where it comes down.
    """
    if len(opp_x) == 0 or len(t) == 0:
        return 1.0
    height = np.nan_to_num(np.asarray(pz, float), nan=0.0)
    low = height <= XPASS["max_height"]
    low[-1] = True
    t, px, py = np.asarray(t, float)[low], np.asarray(px, float)[low], np.asarray(py, float)[low]
    return interception_chance(t, px, py, opp_x, opp_y, opp_vx, opp_vy)


def xpass_features(match, events):
    """xpass_raw: physics-based chance the pass into the hold-up completes (not yet a calibrated probability)."""
    out = pd.DataFrame(np.nan, index=events.index, columns=["xpass_raw"])
    for idx, e in events.iterrows():
        release, contact = int(e.release_frame), int(e.contact_frame)
        snapshot = moving_snapshot(match, release, e.team_id, e.player_id)
        flight = match["frames"].loc[release:contact]
        if snapshot is None or len(flight) < 2 or flight.ball_x.isna().all():
            continue
        sign = attack_sign(match, e.team_id, int(flight.period.iloc[0]))
        flight = flight.iloc[1:]
        flight = flight[flight.ball_x.notna() & flight.ball_y.notna()]
        if flight.empty:
            continue
        t = (flight.frame.to_numpy() - release) / FPS
        opp = snapshot["opponents"]
        out.loc[idx, "xpass_raw"] = trajectory_completion(t, flight.ball_x.to_numpy() * sign, flight.ball_y.to_numpy() * sign,
                                                         flight.ball_z.to_numpy(), opp["x"], opp["y"], opp["vx"], opp["vy"])
    return out


def all_features(match, events):
    """Every feature of the final model for the events of one match, plus the line columns the model also uses."""
    parts = [pass_features(match, events), xpass_features(match, events), pressure_features(match, events),
             support_features(match, events, "contact_frame", "sup_"),
             support_features(match, events, "release_frame", "suprel_"), prereceipt_features(match, events),
             events[["past_line_contact", "line_dist_release"]]]
    features = pd.concat(parts, axis=1)
    features.insert(0, "event_id", events.event_id.to_numpy())
    return features
