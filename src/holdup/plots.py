"""Charts used by the notebooks."""
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

from .data import attack_sign
from .detection import box_edges, find_back_line, frame_snapshot
from .model import calibration_slope, calibration_table, score

GREEN, RED, BLUE, ORANGE, GREY = "#2a9d5c", "#d64545", "#3A4E80", "#D9761F", "#888888"


def clean_axes(ax):
    ax.spines[["top", "right"]].set_visible(False)


# ---------------------------------------------------------------- pitch pictures

def draw_pitch(ax, length=105, width=68):
    ax.add_patch(Rectangle((-length / 2, -width / 2), length, width, fill=False, ec="#999"))
    ax.plot([0, 0], [-width / 2, width / 2], c="#999", lw=0.8)
    for x_start in (-length / 2, length / 2 - 16.5):
        ax.add_patch(Rectangle((x_start, -20.16), 16.5, 40.32, fill=False, ec="#999", lw=0.8))
    ax.set_aspect("equal")
    ax.axis("off")


def draw_event_frame(ax, match, event, frame, title=""):
    """One tracking frame of a hold-up on the whole pitch: the back line (red rings), its box (green), the striker
    (cyan), his teammates (white), the opponents (red) and the ball (gold). The striker's team attacks to the right."""
    draw_pitch(ax)
    snapshot = frame_snapshot(match, int(frame), event.team_id, event.player_id)
    if snapshot is None:
        ax.text(0, 0, "striker not tracked", ha="center")
        return
    rows = match["tracking"].loc[[int(frame)]]
    sign = attack_sign(match, event.team_id, int(rows.period.iloc[0]))
    mates = rows[(rows.team_id == event.team_id) & (rows.player_id != event.player_id)]
    ax.scatter(mates.x * sign, mates.y * sign, c="white", s=55, edgecolor="#555", zorder=3)
    ax.scatter(snapshot["opp_x"], snapshot["opp_y"], c="#ff6f61", s=55, zorder=3)
    line = find_back_line(snapshot["opp_x"], snapshot["opp_y"])
    if line is not None:
        x_low, x_high, y_low, y_high = box_edges(line)
        ax.add_patch(Rectangle((x_low, y_low), x_high - x_low, y_high - y_low, fc=GREEN, alpha=0.13, ec=GREEN, lw=1.4, zorder=1))
        ax.axvline(line["height"], ls="--", c="#666", lw=1, zorder=1)
        ax.scatter(snapshot["opp_x"][line["members"]], snapshot["opp_y"][line["members"]], s=170, facecolors="none",
                   edgecolors="#c0392b", lw=1.5, zorder=4)
    ax.scatter([snapshot["ball_x"]], [snapshot["ball_y"]], c="gold", s=70, edgecolor="k", zorder=6)
    ax.scatter([snapshot["striker_x"]], [snapshot["striker_y"]], c="cyan", s=170, edgecolor="k", zorder=5)
    ax.set_xlim(-53, 53)
    ax.set_ylim(-35, 35)
    if title:
        ax.set_title(title, fontsize=8)


# ---------------------------------------------------------------- model pictures

def plot_calibration(ax, y, p, title):
    """Predicted vs observed retention in equal-count bins, with the log loss, AUC and calibration slope."""
    table = calibration_table(y, p, 6)
    ax.plot([0, 1], [0, 1], c="k", ls="--", lw=1)
    ax.scatter(table.predicted, table.observed, s=table.n * 1.2, c=BLUE, alpha=0.8, zorder=3)
    slope, intercept = calibration_slope(y, p)
    result = score(y, p)
    ax.set_title(f"{title}: log loss {result['log_loss']:.3f}, AUC {result['auc']:.2f}\nslope {slope:.2f}, intercept {intercept:.2f}", fontsize=10)
    ax.set_xlabel("mean predicted retention")
    ax.set_ylabel("observed retention")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    clean_axes(ax)


def plot_waterfall(ax, scores, title):
    """Average xR at release -> set-up added -> xR at contact -> duel added -> kept, per 100 hold-ups."""
    release, setup = scores.xr_release.mean() * 100, scores.setup.mean() * 100
    contact, duel, kept = scores.xr_contact.mean() * 100, scores.duel.mean() * 100, scores.retained.mean() * 100
    steps = [("xR at\nrelease", 0, release, BLUE), ("set-up\nadded", release, release + setup, GREEN if setup >= 0 else RED),
             ("xR at\ncontact", 0, contact, BLUE), ("duel\nadded", contact, contact + duel, GREEN if duel >= 0 else RED),
             ("kept", 0, kept, ORANGE)]
    for i, (label, low, high, colour) in enumerate(steps):
        ax.bar(i, high - low, bottom=low, color=colour, width=0.6)
        text = f"{high - low:+.1f}" if label.split("\n")[0] in ("set-up", "duel") else f"{high:.1f}"
        ax.text(i, max(low, high) + 1.5, text, ha="center", fontsize=9)
    ax.set_xticks(range(5))
    ax.set_xticklabels([s[0] for s in steps], fontsize=8)
    ax.set_ylim(0, 100)
    ax.set_ylabel("per 100 hold-ups")
    ax.set_title(title, fontsize=10)
    clean_axes(ax)


# ---------------------------------------------------------------- player pictures

def z_scatter(player_stats, x_metric, y_metric, xlabel, ylabel, colour=BLUE, note=None):
    """Scatter of two z-scores (shrunk estimates) for the rated strikers. One typical 90% interval is drawn in the
    corner (drawing every interval would swamp the plot: they are several z-scores wide)."""
    rated = player_stats[player_stats.rated & player_stats[f"{x_metric}_z_shrunk"].notna() & player_stats[f"{y_metric}_z_shrunk"].notna()]
    x, y = rated[f"{x_metric}_z_shrunk"], rated[f"{y_metric}_z_shrunk"]
    fig, ax = plt.subplots(figsize=(9, 7.5))
    ax.scatter(x, y, c=colour, s=45, zorder=3)
    for _, r in rated.iterrows():
        ax.annotate(r.player.split()[-1], (r[f"{x_metric}_z_shrunk"], r[f"{y_metric}_z_shrunk"]), fontsize=8,
                    xytext=(4, 4), textcoords="offset points")
    ax.axhline(0, c="k", lw=0.8)
    ax.axvline(0, c="k", lw=0.8)
    limit = float(np.nanmax(np.abs(np.r_[x, y]))) + 0.6
    ax.set_xlim(-limit, limit)
    ax.set_ylim(-limit, limit)
    half_x = float(((rated[f"{x_metric}_z_hi"] - rated[f"{x_metric}_z_lo"]) / 2).median())
    half_y = float(((rated[f"{y_metric}_z_hi"] - rated[f"{y_metric}_z_lo"]) / 2).median())
    ax.errorbar([limit - 0.9], [-limit + 0.9], xerr=min(half_x, 0.85), yerr=min(half_y, 0.85), fmt="o", color=ORANGE,
                ecolor=ORANGE, capsize=3, lw=1.6)
    ax.text(0.98, 0.11, f"typical 90% interval: +/-{half_x:.1f} and +/-{half_y:.1f} z (bar clipped)",
            transform=ax.transAxes, ha="right", fontsize=8, color=ORANGE)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    r = np.corrcoef(x, y)[0, 1]
    ax.text(0.02, 0.02, f"correlation of the two z-scores: {r:+.2f}" + (f"  |  {note}" if note else ""),
            transform=ax.transAxes, fontsize=9, color=GREY)
    clean_axes(ax)
    plt.tight_layout()
    plt.show()
    return r


def forest_plot(player_stats, metric, title, points=100):
    """Shrunk estimate and 90% interval of every rated striker for one score (open dot = raw average)."""
    rated = player_stats[player_stats.rated & player_stats[f"{metric}_shrunk"].notna()].sort_values(f"{metric}_shrunk")
    y = np.arange(len(rated))
    fig, ax = plt.subplots(figsize=(8, 0.3 * len(rated) + 1.5))
    ax.hlines(y, rated[f"{metric}_lo"] * points, rated[f"{metric}_hi"] * points, color=ORANGE, lw=4, alpha=0.4)
    ax.scatter(rated[f"{metric}_shrunk"] * points, y, c=ORANGE, s=40, zorder=3, label="shrunk estimate")
    ax.scatter(rated[f"{metric}_raw"] * points, y, facecolors="none", edgecolors=BLUE, s=40, zorder=3, label="raw average")
    ax.axvline(rated[f"{metric}_league_mean"].iloc[0] * points, c="k", lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{p} ({int(n)})" for p, n in zip(rated.player, rated.n_holdups)], fontsize=8)
    ax.set_xlabel(f"{title}, points per 100 hold-ups (90% interval)")
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    clean_axes(ax)
    plt.tight_layout()
    plt.show()


def scenario_chart(scenario_players, keys, colours=(BLUE, ORANGE)):
    """Shrunk retention over expected of chosen strikers in each scenario, with 90% intervals; the black tick is the
    league mean of that scenario and the open dot the striker's raw average."""
    names = list(scenario_players.scenario.unique())
    fig, ax = plt.subplots(figsize=(10.5, 1.9 * len(names) + 1))
    base = np.arange(len(names))[::-1] * 2.4
    for j, (key, colour) in enumerate(zip(keys, colours)):
        offset = 0.35 - 0.7 * j
        for i, name in enumerate(names):
            table = scenario_players[(scenario_players.scenario == name) & (scenario_players.key == key)]
            y = base[i] + offset
            if table.empty:
                ax.text(1.02, y, "no hold-ups", transform=ax.get_yaxis_transform(), va="center", fontsize=9, color=GREY)
                continue
            r = table.iloc[0]
            ax.hlines(y, r.lo * 100, r.hi * 100, color=colour, lw=6, alpha=0.35)
            ax.scatter(r.shrunk * 100, y, c=colour, s=70, zorder=3)
            ax.scatter(r.raw * 100, y, facecolors="none", edgecolors=colour, s=70, lw=1.6, zorder=3)
            ax.text(1.02, y, f"{r.shrunk * 100:+.1f}   (raw {r.raw * 100:+.1f}, n={int(r.n)})", transform=ax.get_yaxis_transform(),
                    va="center", fontsize=9)
    for i, name in enumerate(names):
        mean = scenario_players[scenario_players.scenario == name].scenario_mean.iloc[0]
        ax.plot([mean * 100] * 2, [base[i] - 1.0, base[i] + 1.0], c="k", lw=1.4)
    ax.axvline(0, c="#aaa", lw=0.8)
    ax.set_yticks(base)
    ax.set_yticklabels(names)
    ax.set_xlabel("retention over expected, points per 100 hold-ups: shrunk estimate and 90% interval")
    for key, colour in zip(keys, colours):
        ax.scatter([], [], c=colour, label=key.split(" | ")[0] + " (shrunk)")
    ax.scatter([], [], facecolors="none", edgecolors="k", label="raw mean in the scenario")
    ax.legend(loc="lower right", fontsize=8)
    clean_axes(ax)
    plt.tight_layout()
    plt.show()
