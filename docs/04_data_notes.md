# Data notes

Findings from pulling the SkillCorner open data on 28 Oct 2026 (`scripts/download_data.py`, `scripts/inspect_data.py`). Column meanings come from the SkillCorner Dynamic Events and Phases of Play CSV specifications (16 Feb 2025).

## What was pulled

- **20 matches**, not 10: the repo README says 10, but `data/matches/` holds 20 folders. The spec's "20" is right.
- Per match, into `data/raw/<id>/`: `_match.json`, `_dynamic_events.csv` (~4 MB), `_phases_of_play.csv` (~0.1 MB). About 90 MB in total. Not committed (`data/` is git-ignored).
- **Tracking not yet downloaded.** `_tracking_extrapolated.jsonl` is a Git LFS pointer (133 bytes) in the repo; the real file is ~90 MB per match (~1.8 GB for 20), fetched from `media.githubusercontent.com` by `python scripts/download_data.py` (drop `--no-tracking`). The script refuses to save a file under 1 MB as tracking.

## Dynamic events: what is there

94,361 rows, 322 columns, over four event types: `passing_option` (48,308), `player_possession` (18,710), `on_ball_engagement` (17,445), `off_ball_run` (9,898).

| Need | Column(s) | Notes |
| --- | --- | --- |
| Reception | `start_type == pass_reception` on `player_possession` | 12,709 receptions |
| Forward | `player_position` in CF / LF / RF | 1,223 receptions (1,098 CF only; pilot found 1,085 striker receptions) |
| Open play | `start_type` excludes throw-in, free-kick, goal-kick and corner receptions; `game_interruption_before` is empty on all forward receptions; `team_in_possession_phase_type != set_play` for extra safety | |
| Outcome | `end_type`: pass, possession_loss, shot, clearance, foul_suffered, unknown; `pass_outcome` | Cross-check against the 3 s tracking rule |
| Aerial | `high_pass` (ball above 1.8 m; True or empty for incomplete passes), `is_header` | |
| Data quality | `is_player_possession_start_matched`, `is_previous_pass_matched`, `is_pass_reception_matched`, `fully_extrapolated` | 1,209 of 1,223 forward starts and 1,203 previous passes matched |
| Last line (SkillCorner's own) | `last_defensive_line_x_start/_end`, `delta_to_last_defensive_line_start/_end/_gain`, `last_defensive_line_height_*`, `organised_defense`, `defensive_structure` | Baseline to compare our back-line algorithm against |
| Separation | `separation_start/_end/_gain` | Nearest opponent, metres |
| EPV (12 columns, possession rows only) | `possession_epv_for_start/_end`, `possession_epv_delta_for`, `pass_reception_epv_for`, `pass_epv_delta_for` and the `_against` / `_total` versions | |
| Labels for validation | `overall_pressure_start/_end`, `reception_difficulty_start`, `passing_option_ease_start/_end`, `space_constraint_start`, `time_to_impact_start/_end` (each with `_id`, 1-5) | Possession rows only |
| Phases | `phase_index`, `team_in_possession_phase_type`, `team_possession_loss_in_phase`, plus a separate phases CSV | Phase of a possession is the phase at its end; 'disruption' (id 14) does not break a phase |

## Conventions and gotchas

- **Coordinates** are metres, pitch centre (0, 0), already mirrored so the team in possession attacks left to right. The README warns they are not scaled to a standard pitch, so use pitch size from `_match.json` where it matters. Tracking is not mirrored: normalise it per period (goalkeeper mean x).
- `event_id` is unique only within a match; key on `(match_id, event_id)`.
- Frames are 10 fps and share the tracking frame numbering (`frame_start`, `frame_end`).
- Each passing option and off-ball run belongs to exactly one player possession (`associated_player_possession_event_id`).
- Possession ends 30 s after the last event; out-of-play has no phase.
- Passing-option events exist only during player possessions, never on set pieces or restarts.
- SkillCorner only releases matches with player and ball quality above 4.
- Receptions via `pass_reception` have a previous pass; link to it for the release frame (previous possession by the same team ending in `pass`).

## Still to confirm

- First touch: whether SkillCorner logs scuffed or lost first touches as player possessions (component-choices rule needs this).
- Release frame: confirm the previous possession's `frame_end` matches the pass frame, using `is_previous_pass_matched`.
- First-touch rule: the detector only sees receptions SkillCorner logged as player possessions.

## Restarts and failed hold-ups in SkillCorner events

- `goal_kick_reception`, `throw_in_reception`, `free_kick_reception` and `corner_reception` mark the player **taking** the restart (a one-frame possession), not the receiver. A forward who receives a restart pass is an ordinary `pass_reception` whose previous possession is the taker's pass, so the detector links it normally and labels `origin` from the taker's start type.
- A hold-up where the defender wins the ball is an unsuccessful pass with `player_targeted_id`/`player_targeted_position` set to the forward, followed by an opponent possession with `start_type = pass_interception`. First contact for these is the frame the ball comes closest to the forward (ball within 5 m), not the interceptor's first frame.

## Detection results (notebook `01_event_detection.ipynb`, 20 matches, CF/LF/RF)

Updated 29 Oct 2026: a defender being close at first contact is no longer a detection rule (the striker only has to be posted on the back line), so that how well he gets away from defenders can be assessed afterwards. The engaged gate is still in the code, off by default (`require_engaged`).

- Tracking and events agree exactly on the striker's position at first contact (median difference 0.00 m).
- Candidates: 1,825 = 1,223 received + 602 defender-first. Restart passes among linked candidates: 8 goal kicks, 32 throw-ins, 18 free kicks, 12 corners.
- The attacking-half rule is optional and off. 285 of the 989 events that reach that stage have the striker in his own half at release.
- Funnel at defaults (band 10 m, ball angle 45 degrees, max gap 5 s, no attacking-half or engaged gate): 1,825 candidates → 1,584 linked → 989 from behind → 839 on the line → **599 hold-ups** (435 received, 164 defender first), 14.97 per team-match (pilot about 2.7), 58 forwards with at least one.
- Sensitivity, hold-ups by band and by how engaged is treated: band 2.5 m = 261 with no engaged rule (121 / 159 / 197 if a defender within 2.5 / 3.5 / 5 m were required), 5 m = 423 (190 / 251 / 315), 10 m = 599 (257 / 327 / 424), 15 m = 694 (304 / 376 / 486). By max ball angle: 30 / 45 / 60 / 90 degrees / off = 435 / 599 / 702 / 824 / 928. By min_x: none / halfway line / 10 m past = 599 / 448 / 307. With the engaged rule on, the time-to-reach limit 0 / 0.5 / 1.0 / 1.5 s gives 284 / 288 / 327 / 370 and the defender angle 90 / 110 / 135 / 180 degrees gives 301 / 327 / 374 / 427.
- The volume is well above the pilot's. With a 10 m band many events have the striker well in front of the back line with defenders between him and it; tightening the band (2.5 m gives 261) is the main lever. Decide from clip review before modelling.

## Pass flight time (`max_gap`)

Notebook section 5. Gap is frames from pass release to first contact (10 per second); it affects only the linked gate, so the sweep is one run filtered to each limit.

| max_gap | 20 (2 s) | 30 (3 s) | 40 (4 s) | 50 (5 s) | 60+ |
| --- | --- | --- | --- | --- | --- |
| Linked candidates | 1,244 | 1,485 | 1,559 | 1,584 | 1,584-1,586 |
| Hold-ups | 440 | 545 | 589 | 599 | 599-600 |

- The count stops growing at 50 frames (one received hold-up arrives after 6.2 s). The 5 s default captures essentially everything.
- A 3 s limit would lose 55 of 600 hold-ups (9%), mostly balls the defender won.
- Median ball travel by flight time: under 1 s = 8.5 m, 1-2 s = 15.3 m, 2-3 s = 27.9 m, 3-4 s = 39.5 m. The share where the defender won it rises from 7% (under 1 s) to 18% (1-2 s), 57% (2-3 s) and 75% (3-4 s): the longer a ball is in the air, the more often the defender gets there first.

## Outcomes (notebook `02_outcomes.ipynb`, 3 s window, 599 hold-ups)

- Split: 276 kept, 11 foul won, 296 lost (164 defender first, 132 after he received it), 16 own shot.
- Retention (kept + foul won over kept + foul won + lost, shots excluded): **68.5%** of balls he received (287 of 419, 90% interval 64.7-72.1%; pilot 60%) and 49.2% over all candidates including defender-first failures. Counting own shots as kept gives 69.7% of received.
- Reasons for the 132 received-and-lost: 55 possession losses, 58 unsuccessful passes, 14 opponent possession in the window, 2 clearances, 1 offside, 2 ball out against.
- Window: retention of received balls is 75.7% at 2 s, 68.5% at 3 s, 62.2% at 4 s, 55.3% at 5 s. For the 37 players with at least 6 hold-ups, the ranking at 3 s correlates 0.95 (2 s), 0.97 (4 s) and 0.93 (5 s) with the other windows, so rankings hold.
- Median time on the ball: kept 1.1 s, lost 0.9 s, foul won 0.7 s, own shot 1.3 s.
- SkillCorner's tracking possession flag at first touch + 3 s agrees with the event labels 71% of the time for received balls (53% for defender-first), so the event data is the source of truth.
- Raw per-player retention is still noisy (most forwards have 15-30 hold-ups); wait for expected retention before ranking.
- Open: a defender-first ball is always counted lost, even when his team regains it within 3 s; this follows the 'defender touched it first' rule but is worth revisiting.

## Pass difficulty features (notebook `03_pass_difficulty.ipynb`, 599 hold-ups)

- Ball tracking is good over the flight: median 100% of frames detected, 22 hold-ups below 80%, no missing ball heights.
- SkillCorner's `high_pass` is only recorded for resolved passes: tracking finds 148 more balls with a peak above 2 m than the flag marks (and only 4 flagged balls peak below 2 m), so the aerial flag is the event flag or a peak above 2 m. 37% of hold-ups are aerial.
- Retention, aerial vs ground: 22% vs 65% (n = 215 and 368).
- Univariate AUC for predicting a lost ball: contact height 0.76, peak height 0.76, aerial 0.70, pass distance 0.65, flight time 0.64, ball speed 0.57, striker width 0.46. Deeper origin raises the chance of losing it (origin_x AUC 0.35) and more oblique balls are kept more (pass_angle_abs 0.39), probably confounded with lofted balls from deep.
- Overlap: peak height and contact height correlate 0.91, pass distance and flight time 0.84, peak height and the aerial flag 0.83, pass distance and origin x -0.65. The model must handle this (regularised or boosted), not hand weights.
- Against SkillCorner's reception difficulty label (1-5, 404 received hold-ups with labels), Spearman: peak height 0.72, contact height 0.65, aerial 0.63, pass distance 0.40, ball speed 0.35, flight time 0.26. Against overall pressure and passing option ease the correlations are 0.35 at most, so these features are about the pass, not the pressure.

## Pressure models (notebook `04_pressure.ipynb`, 599 hold-ups)

- **Pressing intensity** (Bekkers-style): each defender keeps his velocity for 0.7 s, then runs at the striker at 7 m/s; the reach time becomes a probability of arriving within 1.5 s (logistic, sigma 0.45 s). One deviation of mine: a defender whose reaction-phase path already passes within 1 m of the striker has reached him. Without it, a fast-closing defender overshoots in the projection and looks far away.
- **Pressure oval** (Andrienko/Herold-style): each defender adds (1 - d)^1.75 inside an oval reaching 9 m goal-side, 3 m behind and 6 m sideways (the 6 m is my assumption).
- Correlation with SkillCorner's labels (411 received hold-ups, first contact), overall pressure / space constraint / time to impact: nearest defender distance -0.78 / -0.57 / -0.87; oval sum 0.72 / 0.60 / 0.79; defenders within 3 m 0.70 / 0.53 / 0.77; pressing intensity (chance at least one arrives) 0.55 / 0.61 / 0.62; its sum 0.40 / 0.61 / 0.38. SkillCorner's labels look largely distance-based, which favours the distance and oval measures.
- Predicting retention (logistic regression on the pass features, 100 splits holding out whole matches): baseline log loss 0.596 against 0.698 for the base rate. Best single additions: defenders within 5 m -0.0150, nearest defender distance -0.0101, oval sum -0.0075, pressing intensity sum -0.0053; contact plus release distance measures -0.0113. All are modest (about 2.5% of log loss at best) but consistent across splits.
- Sensitivity: the sum of pressing probabilities correlates 0.19 to 0.63 with the overall pressure label across 27 settings of reaction time, top speed and time limit.
- This changed when the engaged gate was dropped: on the earlier gated sample (327 hold-ups, defender always close) pressing intensity correlated only 0.04 to 0.25 with the labels and no pressure measure improved the fit by more than 0.005. With the full range of separation in the data, pressure carries real signal.
- Pass difficulty is still the stronger driver of retention; pressure adds a smaller, consistent gain on top.

## Support options (notebook `05_support.ipynb`, 599 hold-ups)

- Per hold-up at first contact, team-mates within 30 m (own goalkeeper excluded): on average 6.5 in reach, nearest 9.4 m away, 1.7 open geometric lanes (no opponent within 2 m of the line, team-mate's nearest opponent more than 3 m away), 2.6 free by the pressing-intensity measure, 1.5 options at 70%+ expected completion, 3.2 running towards him faster than 1 m/s. Most good options are behind him (1.05 at 70%+) rather than level (0.34) or ahead (0.15).
- **Completion model**: the ball travels at 14 m/s from the striker to the team-mate; each opponent (goalkeeper included) can intercept at any point on the path he reaches no later than the ball (reaction 0.5 s, then 7 m/s from his velocity-projected position, logistic margin with sigma 0.4 s); completion is the product of one minus the best interception chance per opponent. Constants are hand-set. Sanity checks: an open 15 m pass completes at 1.00, a defender 1 m from the line mid-way gives 0.60, a defender on the line near the receiver gives 0.13.
- The geometric lane is much stricter than the completion model (an event can have two 70%+ options and zero open lanes), because the marker-within-3-m rule blocks any team-mate who is tightly marked.
- Agreement with SkillCorner (411 received hold-ups with labels): open lanes -0.46, best expected completion -0.45 and 80%+ options -0.42 against the passing-option-ease label (higher label = more constrained, so negative is the right sign); the sum of expected completions correlates 0.44, and options at 60%+ 0.42, with SkillCorner's count of passing options at the start of the possession.
- AUC for predicting a lost ball: options at 60%+ 0.40, sum of completions 0.41, options at 70%+ 0.43, open lanes 0.43, free team-mates 0.43. Team-mates in reach is no signal (0.53), and the further away they are the more often the ball is lost (mean distance 0.57).
- Cross-validated gain on top of pass features plus defenders within 5 m and oval pressure (baseline log loss 0.5829): options at 60%+ -0.0064 (better in 73% of splits), sum of completions -0.0040, options at 80%+ -0.0024, at 70%+ -0.0021, open lanes -0.0012. Free team-mates, number approaching and the direction split add nothing; all support measures together are worse (+0.0052) because they overlap heavily.
- Sensitivity: the correlation of options at 70%+ with SkillCorner's ease label ranges -0.17 to -0.48 across ball speeds of 10-18 m/s and reaction times of 0.3-0.7 s, so the completion constants matter and the threshold choice should be checked in the final model. A lower threshold (60%) fits retention best; a higher one (80%) agrees best with SkillCorner's label.
- Support was measured at first contact only; the spec's planned extension (how support changes while he holds the ball) is not built.

## Pre-receipt actions (notebook `06_pre_receipt.ipynb`, 599 hold-ups)

- Separation from the nearest defender, release to first contact: **26% of hold-ups gain separation**, median change -0.92 m (4.5 m at release, 3.4 m at contact on average); 15% lose more than 2 m. Following the specific defender who was nearest at release (the marker), 38% gain distance on him, median -0.45 m. Kept and lost balls look alike on separation gain (median -1.17 vs -1.12 m); defender-first balls show a smaller loss (-0.43 m), but their first contact is where the ball came closest, not a real touch.
- Movement: median check-short -0.2 m (most strikers run on rather than drop), sideways movement 1.9 m median, speed at first contact 3.4 m/s on average (fastest during the flight 4.0), 0.5 m/s faster than at release. Back line height (metres from the opposition goal line) averages 39.6 m, from 10 to 90 m, because the attacking-half rule is off.
- AUC for predicting a lost ball: acceleration 0.66, back line height 0.64, path length 0.62, speed at contact 0.61, forward speed 0.58; separation level at release or contact 0.40 (more space goes with keeping it), separation gain 0.545, marker gain 0.54, goal-side gain 0.525. So the level of space matters, the change does not.
- Cross-validated gain on top of pass + pressure + support (baseline log loss 0.5765): acceleration -0.0040 (better in 78% of splits), back line height -0.0027, check-short -0.0021, speed at contact -0.0018. Separation gain (+0.0027), marker gain (+0.0032) and the separation combination (+0.0047) make the fit worse, as does using all pre-receipt measures (+0.0104). Faster and accelerating strikers lose it more often (a ball taken on the run is harder to control), as do those facing a high line.
- Interpretation caution: separation gain here is mostly a function of where the defenders are (they close in during the flight for nearly everyone); the planned set-up added measure (step 12) will adjust for that.
- **Step 2 closed**: SkillCorner's `last_defensive_line_x_start` equals the deepest outfield defender at first contact (435 received hold-ups, correlation 1.00, median difference 0.00 m); the median-x of our chained back line is 3 m shallower on average (correlation 0.98). The striker's distance to the line matches SkillCorner's `delta_to_last_defensive_line_start` (correlation 0.976).

## Expected retention model (notebook `07_expected_retention.ipynb`, 583 labelled hold-ups, 20 matches)

- **Target** retained (kept or foul won = 1, lost = 0, defender-first balls included as lost, own shots excluded); base rate 49.2%. **Features** (12, all at first contact except the pass): aerial, peak height, flight time, pass distance, origin x; defenders within 5 m, oval pressure; options at 60%+ completion, open lanes; speed, metres past the back line, back line height.
- **Validation against SkillCorner labels (389 received hold-ups)**: peak height 0.72 with reception difficulty; oval pressure 0.72 with overall pressure and 0.79 with time to impact; nearest defender -0.78 / -0.87; open lanes -0.58 with overall pressure and -0.45 with passing-option ease; options at 60%+ -0.35 with ease. Own-state features have no label to check against.
- **Collinearity**: origin x and back line height correlate -0.91 (deep origins come against high lines), aerial and peak height 0.84, flight time and distance 0.84, distance and origin x -0.66, defenders within 5 m and oval 0.61. L2 regularisation and shallow trees handle it; dropping line height leaves the fit unchanged (0.5755).
- **Model comparison** (100 splits holding out 25% of matches; log loss / AUC): base rate 0.698 / 0.50; logistic on pass only 0.596 / 0.74; + pressure 0.583 / 0.76; + support 0.577 / 0.77; + own state (full) 0.575 / 0.77; boosted trees 0.583 / 0.76; **average of logistic and trees 0.572 / 0.77**. Each group adds a little; the trees do not beat the logistic regression at this sample size, but the average helps slightly.
- **Calibration** (10-fold by match, 5 repeats): slope 0.92 (logistic), 0.97 (trees), 1.01 (average); intercepts 0.01-0.02; predicted and observed retention agree in all six equal-count bins. The model separates well: 28% of balls get under 30% and 10% get over 80%.
- **What drives it** (logistic, per standard deviation, 90% interval from resampling matches): peak height -0.91 (-1.31 to -0.64) is dominant (52% of the trees' gain); flight time +0.47 (given peak height, longer flights go with keeping it, probably slower and easier balls; not a causal reading), defenders within 5 m -0.41, options at 60%+ +0.26, speed at contact -0.17, back line height -0.29, aerial -0.24 (interval spans zero given peak height). Oval pressure, distance, origin, open lanes and metres past the line are not distinguishable from zero in the presence of the others.
- **Sensitivity**: swapping 70% options, the sum of completions, pressing intensity or nearest defender for the chosen measures changes log loss by at most 0.008 (nearest defender instead of defenders within 5 m is worst); adding pass angle or acceleration changes nothing; removing the own-state features costs 0.002. Regularisation strength barely matters (C 0.1 to 10: 0.574-0.578).
- **Caveats**: 583 balls from 20 matches is small, so intervals on coefficients are wide and the weak features should not be interpreted individually. The A-League sample is one league and one season, and the model describes average-striker retention, not a particular player's. Out-of-fold xR for each ball is in `data/processed/holdup_xr.csv`.

## Retention over expected (notebook `08_retention_over_expected.ipynb`, 583 labelled hold-ups)

- The same model (average of logistic regression and boosted trees, trained on the first-contact state) is applied to the release state, with the pressure, support, speed and distance-to-line features taken at pass release (support at release is recomputed from tracking). All predictions are out of fold by match.
- **League picture**: observed retention 49.2%; mean xR at release 51.5%, at first contact 49.0%. Mean set-up added is -2.5 points (62% of hold-ups get harder between release and first contact; the middle 80% range from -0.12 to +0.06), mean duel added is +0.2 (the model is calibrated at first contact: slope 1.01), and mean RoE is -2.2. Because the average set-up added is negative for everyone, headline set-up added and RoE are **centred on the league mean**; RoE (centred) = set-up added (centred) + duel added, exactly.
- **What changes during the flight** (log-odds change from the logistic coefficients): pressure -0.17 on average (more defenders within 5 m: 0.81 to 1.15; oval pressure 0.27 to 0.39), support +0.08 (more options at 60%+: 1.5 to 2.0, though fewer open lanes: 2.0 to 1.7), own state -0.02 (faster, 2.8 to 3.3 m/s, and further past the line, -2.9 to -4.1 m).
- **Striker-controlled set-up** (his speed and metres past the line replaced by league averages): mean +1.8 points, standard deviation 3.9 points against 7.8 for the simple set-up added; correlation with it is only 0.24, so most of the simple set-up added is what others do, not the striker.
- **Strikers** (at least 10 hold-ups: 22 strikers, 409 of the 583 hold-ups): spread across strikers (standard deviation per 100 hold-ups) is 1.6 for set-up added and 10.5 for duel added; a typical 90% bootstrap interval is 5.8 wide for set-up and 33 wide for duel. Duel added is far noisier than set-up added, as the spec expected (set-up uses model probabilities on every ball, duel depends on 0/1 outcomes).
- **Reliability**: random split-half within strikers gives Spearman correlations of 0.01 (RoE), -0.15 (set-up added) and -0.02 (duel added), each with a 5th-95th percentile range spanning zero (about -0.4 to +0.3): no detectable difference between these strikers beyond noise. The date split (early vs late matches) has only 6 strikers appearing in both halves, so it is uninformative. By contrast the service a striker receives (xR at release) is stable: split-half correlation 0.64 (0.48-0.79), so strikers do differ systematically in how hard the balls they are given are.
- **Reading**: the framework and the model are in place and calibrated, but this sample (20 matches, a few hold-ups per striker per match) cannot rank strikers on RoE, set-up added or duel added. The expected-retention and service measures are the supportable output now; striker ratings need more matches (roughly the full season for a first-choice striker, as the spec estimated 80-100 hold-ups) or pooled data. Step 14-15 (hierarchical model and shrinkage) will pull the noisy estimates towards the league average, which will largely collapse them at this size.

## Value added (notebook `09_value_added.ipynb`, 572 hold-ups with a value and an outcome)

- **Definition**: before = `possession_epv_for_start` of his possession; after = the EPV at the start of the next possession if it begins within 50 frames (positive if his team has it, negative if the opponent does), otherwise the EPV at the end of his own possession (shots, fouls won, dead balls: about 10% of hold-ups). Value added = after - before. The sign flip on opponent possessions assumes EPV is roughly zero-sum between the teams.
- **Levels**: EPV is small (a typical hold-up starts at 0.037). Mean value added is -2.2 points: retained hold-ups lose almost nothing (-0.3), lost hold-ups lose 4.1. (Two receptions appear twice in the candidate files, once as received and once as defender-first; tables are merged on match, event and outcome so they are not duplicated.) A hold-up is on average a value loss because the ball is usually played back or to a teammate with less threat, and an opponent gets it half the time.
- **Choice of window**: mean value added moves from -1.1 (20 frames) to -2.0 (50) to -2.1 (100 frames); 50 chosen so only about a tenth fall back to the own-possession end.
- **Expected value added** (ridge plus small boosted trees on the retention features and the starting EPV, out of fold by match): R2 0.14, correlation 0.37, against 0.01 from the starting EPV alone. So the situation explains a modest share of the value outcome.
- **Value over expected**: correlation 0.47 with centred RoE and 0.44 with retention; mean +1.5 points for retained and -1.5 for lost. Among retained hold-ups its sd is 3.6 points with no relation to set-up added (-0.04): what he does with the ball after keeping it varies a lot and is not explained by the set-up.
- **Strikers** (22 with at least 10 hold-ups): sd of value over expected across strikers 1.0 point, median 90% interval width 2.2. Random split-half correlation 0.19 (5th-95th percentile -0.04 to 0.42) for value over expected, 0.25 (0.00 to 0.51) for raw value added, 0.00 for RoE. A weak positive signal, but the interval includes zero, so it supports a tentative reading at best.
- **Not run**: the open EPV grid repeat (the grid is not in this data).

## Situational splits and shrinkage (notebook `10_situations_and_shrinkage.ipynb`, 572 hold-ups, 58 strikers)

- **Strikers per sample**: 58 strikers, median 7 hold-ups, maximum 65. All are used; shrinkage is made for small samples.
- **Situational splits** (open play 550 / restart 22; aerial 205 / ground 367; defender within 5 m 471 / free 101; pass distance terciles): mean RoE (centred) is between -1.1 and +3.1 points in every split except "free", whose 90% interval is +0.7 to +14.7 (mean +7.6). The model is calibrated in each: kept is within 2 points of xR at contact in all splits except free (+2.8). Free hold-ups (no defender within 5 m at contact) are rare and the model under-predicts their retention a little, mostly through set-up added (+4.8), so strikers who often get free are slightly flattered.
- **Hierarchical model**: each measure = league mean + striker level + luck. sigma_within is the spread of single hold-ups around the striker's own mean (RoE 46 points, set-up 7.8, value 3.4 EPV points). The real spread sigma_between has a full grid posterior (flat prior): RoE median 2.5 points (90% range 0.2 to 7.2), set-up 0.4 (0.04 to 1.3), duel 2.4 (0.2 to 7.1), value over expected 0.6 (0.1 to 1.1), service (xR at release) 9.8 (7.5 to 12.5).
- **ICC**: RoE 0.003 (largest plausible 0.02), set-up 0.003 (0.03), duel 0.003 (0.02), value over expected 0.03 (0.10), service 0.18 (0.26). Almost none of the hold-up-to-hold-up variation in retention over expected is a stable striker difference; about a fifth of the difficulty of the service is.
- **Shrinkage**: with the largest plausible real spread, a striker with 25 hold-ups keeps only 38% of his raw RoE gap (61% at 65). For value over expected the shares are 72% and 87% at 25 and 65 hold-ups.
- **Shrunk striker estimates** (2,000 draws including the uncertainty about sigma_between): RoE raw range -29 to +64 points collapses to -1.0 to +2.3; value over expected raw -2.9 to +10.1 collapses to -0.6 to +1.0. No striker's 90% interval excludes the league mean for either measure. The top value over expected strikers (Brooke-Smith, Antonsson, Ruhs, Lavale, Douglas Costa) have 0.78-0.88 posterior probability of being above league average, which is a lean, not a finding.
- **Reading**: at this sample size the data supports league-level findings and the service a striker receives; it cannot separate strikers on RoE, set-up or duel.

## Uncertainty (notebook `11_uncertainty.ipynb`, 58 scored strikers, 22 with at least 10 hold-ups)

- **Exposure**: `playing_time.total.minutes_played` and `minutes_tip` (minutes his team had the ball) from each match file. Roster = CF/LF/RF who played, plus anyone with a hold-up: 114 player-matches, 65 players (7 with no hold-up), 6,665 minutes, 1,823 minutes of team possession. Roles in the match file are the starting role, so a forward listed in another role who never had a hold-up is not counted.
- **Hold-up rate**: league rate 8.1 per 90 minutes played, 29.9 per 90 minutes of team possession (high because detection is generous; the pilot had 2.7 per team-match). Gamma-Poisson fit: the true rate varies between strikers by about 21-24% (sd/mean). Most strikers have 1-4 matches, so the raw per-90 rate swings widely (for example Ishige 55 per 90 team-possession minutes raw, 43 shrunk, in 178 minutes) and the shrunk rate and its interval should be the one shown.
- **Measures**: bootstrap (2,000 resamples of his hold-ups) 90% intervals for the raw mean are wide; shrunk estimates (step 14 model) are all within a few points of the league mean. For the top RoE strikers (Machach, Ruhs, Ishige, Kuen, Brimmer) the raw boot interval just misses or includes zero and the shrunk interval always does.
- **Percentile ranks**: in every posterior draw the 58 strikers are ranked. The 90% range of a striker's percentile has median width 89 points (RoE, set-up, duel) and 82 (value over expected), e.g. the top RoE striker is at the 65th percentile with a range of 9 to 98. A percentile alone would claim more than the data supports.
- **Claims that survive**: no striker has a model probability of 0.9 or more of being above (or below) the league average on any of the four measures; one reaches 0.8 (value over expected). The raw bootstrap interval excludes the league mean for 4 (RoE), 4 (duel), 1 (set-up) and 6 (value over expected) of 22, which is roughly what the multiple-comparison noise of 22 intervals gives and is not trusted.
- **Scorecard rule for step 16**: show per 90 rates with their shrunk intervals; show the shrunk measures with their intervals; show percentiles only with their ranges; label any striker below the hold-up threshold as not rated.

## Scorecard (notebook `12_scorecard.ipynb`)

- One page per rated striker (at least 10 hold-ups; 22 strikers), saved as PNG in `reports/scorecards/`. Panels follow the step 15 rules: shrunk estimates with 90% intervals, percentile with its range, league average always marked, raw situational means (unshrunk, with bootstrap intervals) for aerial / ground and defender near / free, and a raw-mean waterfall from xR at release through set-up and duel to retention. Set `PARAMS['striker']` and `PARAMS['compare']` in the notebook to pick strikers.

## Frame QA (notebook `13_frame_qa.ipynb`)

- **Data checks** on all 599 accepted hold-ups: release never after contact, ball inside the pitch at both frames, at least 9 outfield defenders on the pitch at release, striker present in tracking at both frames. None fails. The ball is detected (not extrapolated) at release in 98.5% and at contact in 99.8%; the striker is detected at contact in 99.3% but at release in only 66.6% (the rest are extrapolated, mostly off-camera). Set-up added is the same either way (mean -2.3 points detected, -2.7 extrapolated), so the extrapolation does not bias it, but retention differs a lot (56% vs 36%), so the two groups are different situations (long and aerial balls) and the model has to carry that, which it does through the pass features.
- **Two events appear twice** (match 1899585 event 8_631 and match 2010085 event 8_482: one received and one defender-first candidate from the same reception); tables are merged on match, event and outcome.
- **Contact sheets**: on the accepted events the picture matches the definition: the striker moves to where the ball arrives, the back line is a plausible group of defenders and the ball comes from behind or the side-behind. Defender-first events show the defender first touching the ball within 5 m of him (by construction), most often on long balls into the line.
- **Band**: retention rises with distance from the back line at release (46% at 0-3 m, 46% at 3-5, 55% at 5-7, 58% at 7-10). Candidates rejected only by the band are 82 at 10-14 m and 51 at 14-20 m, and they look the same as the 7-10 m ones: a continuum with no natural edge. Band half-width 5 / 7 / 10 / 14 m gives 423 / 518 / 599 / 681 hold-ups. Since distance to the line enters the model (past_line_contact), the band mostly changes volume, not bias; a narrower band (7 m) is the choice if the intent is "striker is on the line", at a cost of 14% of events.
- **Review template**: `reports/qa/review.csv` lists the 72 sheet events; fill `verdict` (ok / bad / unsure) and `note`; re-running the notebook keeps what was filled in.

## Box detector variant (notebook `14_box_detection.ipynb`, `src/holdup/box_detector.py`)

A separate variant; `detector.py` and `holdups.csv` are untouched. Back line capped at 15 m span or 4 defenders (nearest-to-seed first); the target is a box: depth = line height +/- 10 m (settable front and behind), width = the y extent of the line's own defenders (+ optional margin); judged at release or at first contact (both are stored; `box_flags` re-judges without re-running).

- **Regression check**: with the cap off, no width limit and judged at release, the variant returns exactly the original 599 hold-ups.
- **Counts** (depth 10, no margin, cap 4): 452 judged at release, 430 judged at contact (original band: 599). Of the original 599, 391 (release) and 355 (contact) survive; the box adds 61 and 75 that the band did not accept.
- **Which side rejects**: of 989 linked, from-behind candidates, width rejects 255 (release) / 259 (contact) that depth alone would keep; depth alone rejects 76 / 94. Width is the stricter dimension.
- **Line size**: 4 defenders in 69% of lines; median x span 2.9 m, median box width 25 m. Lines of 1 or 2 members give narrow boxes (median 0 m and 12 m wide; 34% of 2-member boxes contain the striker, vs 62% of 4-member ones), so a 2-defender line is the main way a striker is rejected for width. A `width_margin` of 3 m adds about 100 hold-ups, 6 m about 140.
- **Release vs contact**: the striker moves 5.8 m between release and first contact and the line moves 3.6 m. 482 of 989 candidates are in the box at both moments, 94 only at release, 52 only at contact, 361 at neither.
- **Retention**: 42.1% (box at release) and 40.4% (box at contact) against 49.2% for the band; defender-first share 35% / 37% against 27%. The box keeps events where he is pinned inside the line's width, which are harder.
- **Fixed half-width for lines of 1-2 defenders** (`small_half_width`, applied to the middle of those defenders; the width margin is not applied to them). Swept 3 to 25 m: hold-ups at release 421 (3 m), 442 (5), 464 (7.5), 479 (10), 497 (12.5), 498 (15), 506 (20), 507 (25) against 452 with the extent only; at contact 413, 427, 444, 460, 471, 475, 484, 486 against 430. Counts flatten after 12.5-15 m (a normal 3-4 defender line is about 25 m wide, so 12.5 m either side matches it). Below about 5 m a fixed width is narrower than the extent of some 2-defender lines and removes events. Hold-ups from 1-2 defender lines go from 62 to 107-117 (release) at 12.5-25 m. The events a fixed width adds retain less (release: 0.29 at 7.5 m, 0.31 at 10, 0.39 at 12.5; contact: 0.19, 0.21, 0.23) than the box overall (0.41-0.42), and total retention moves only about a point. Among 110 small-line candidates at contact, retention does not change in a clear way with the striker's lateral distance from the middle (0.22 at 0-4 m, 0.12 at 4-8, 0.23 at 8-12), so the data does not pick a half-width; the sample is small.
- **Flexible small-line rule adopted as the notebook default: extent + 5 m** (`small_margin`; one defender: his y +/- 5 m; two defenders: from one to the other plus 5 m each side; the fixed half-width option remains). Box variant with cap 4, depth 10 m: 491 hold-ups judged at release (101 from 1-2 defender lines, retention 41.4%) and 472 judged at contact (93 from small lines, retention 38.9%), against 599 for the band. Compared with extent only (452 / 430) the 5 m margin adds 39 / 42 events, mostly from small lines; margins of 2.5, 5, 7.5 and 10 m give 480, 491, 497, 501 at release, so the counts level off above 5 m. Of the original 599, 429 (release) and 395 (contact) are kept; the box adds 62 and 77. Width still rejects 208 / 214 linked, from-behind candidates that depth alone would keep.

## Whole pipeline on the box detector (`notebooks/box/02` to `12`, `data/processed_box/`, `reports/box/scorecards/`)

Copies of notebooks 02-12 run on the box detections (judged at first contact, cap 4, depth 10 m, 1-2 defender lines extent + 5 m: 472 hold-ups, 460 with an outcome label). The original results in `data/processed/` and `notebooks/` are untouched. Prose in the copies still quotes the original numbers; the code outputs are live.

- **Outcome**: retention 38.9% (original 49.2%); the box selects harder, more pinned situations.
- **xR model** (same design): out-of-fold log loss 0.560 (base rate 0.674), AUC 0.77, calibration slope 1.04, mean xR 0.388 vs observed 0.389. Peak height still dominates; pressure (defenders within 5 m, coefficient -0.46) and support (+0.41) are clearer than before.
- **Set-up / duel**: mean xR at release 39.8%, at contact 38.8%; set-up added averages -1.0 points (original -2.5) and 54% of hold-ups get harder (62%). Because the box is judged at first contact, the striker is by construction inside the line's box at contact, which trims the set-up loss; set-up added is partly a selection effect of this choice. Controlled set-up correlates 0.29 with the simple one.
- **Strikers**: 17 with at least 10 hold-ups (16 with a value). Random split-half correlations: RoE 0.24 (5th-95th -0.08 to 0.54), set-up added -0.11, duel 0.24, xR at release 0.47. Better than the band set (0.01) but the RoE range still includes zero.
- **Value**: mean value added about -2.5 points; value over expected correlates 0.50 with RoE; split-half 0.41 (0.17 to 0.69) with 16 strikers. A few large positive value events (single values up to +28 points) pull on this; one striker with a single hold-up and a +28 point value reaches a 0.96 probability of being above average, which is a symptom of heavy tails in the value measure and the normal random-effects model, not evidence.
- **Hierarchical**: ICC RoE 0.003 (largest plausible 0.03), value over expected 0.09 (0.20), service 0.11 (0.19); 0 of 55 strikers have a shrunk RoE interval excluding the league mean, 3 of 55 for value over expected.
- **Rates**: 6.3 hold-ups per 90 minutes played, 23.7 per 90 minutes of team possession; true rates vary about 36-45% between strikers.
- **Percentiles**: still 89-91 points wide for RoE, set-up and duel.
- **Scorecards**: 16 strikers rated (at least 10 hold-ups), in `reports/box/scorecards/`.

## Whole pipeline on the box detector, either moment (`notebooks/box_either/02` to `12`, `data/processed_box_either/`, `reports/box_either/scorecards/`)

Box judged at pass release **or** at first contact (`eval_at='either'`; union of the two single-moment sets), cap 4, depth 10 m, 1-2 defender lines extent + 5 m: 535 hold-ups (521 with an outcome). Contact-only results are in `notebooks/box/`, the band results in `notebooks/` (all untouched).

- **Outcome**: retention 40.5% (band 49.2%, contact only 38.9%, release only 41.4%).
- **xR model**: log loss 0.564, AUC 0.77, calibration slope 1.02, mean xR 0.405 vs observed 0.405.
- **Set-up / duel**: mean set-up added -0.8 points (contact only -1.0, band -2.5), 54% of hold-ups get harder; the union does not bring set-up added back towards the band value, so the shift is not only a contact-selection effect (my earlier expectation of about -1.5 to -2 was wrong). Controlled set-up correlates 0.32 with the simple one.
- **Strikers**: 21 with at least 10 hold-ups (21 with a value; band 22, contact only 17). Random split-half correlations: RoE 0.07 (5th-95th -0.20 to 0.35), set-up added -0.20, duel 0.03, xR at release 0.49, value over expected 0.26 (0.03 to 0.48), raw value added 0.26.
- **Hierarchical**: ICC RoE 0.003 (largest plausible 0.02), value over expected 0.02 (0.08), service 0.10 (0.17). 0 of 56 strikers have a shrunk RoE or value-over-expected interval excluding the league mean. Percentile ranges 85-91 points wide. Raw bootstrap intervals exclude the league mean for 1 (RoE), 1 (set-up), 1 (duel) and 5 (value) of 21.
- **Value**: R2 of expected value added 0.16; value over expected correlates 0.49 with RoE.
- **Rates**: 7.0 hold-ups per 90 minutes played, 26.4 per 90 minutes of team possession.
- **Reading**: with more strikers rated, the correlations that looked promising for the contact-only set (value over expected 0.41) weaken to 0.26 and RoE 0.24 to 0.07, so those gains were largely sample-specific; the conclusions of the band pipeline hold: only the service a striker receives is stable.
- **Scorecards**: 21 strikers rated.

## Expected pass completion, z-scores and scenarios (notebooks `16`, `15`; `notebooks/box_either_xpass/`, `data/processed_box_either_xpass/`)

- **Expected pass completion** (`src/holdup/xpass.py`, notebook 16): the chance the pass into the hold-up gets through, from the ball's actual path (position, height, timing) against every opponent at pass release (reaction 0.5 s, 7 m/s, logistic margin 0.4 s; a defender can only play the ball where it is at most 2 m high, and the contested end point always counts), then Platt-calibrated out of fold by match to completed vs intercepted. 64.5% of the passes complete. Calibrated version: AUC 0.725, log loss 0.565 (base 0.648), well calibrated; SkillCorner's own `player_targeted_xpass_completion` (88.9% coverage): AUC 0.752, log loss 0.534; the flat-ball version: AUC 0.669. Aerial balls average 0.51 against 0.75 for ground balls. Correlation with peak height -0.61. A weakness: for lofted balls the raw physical value is close to zero for many passes, so the calibrated value bunches near 0.3 and cannot rank among them.
- **In the retention model** (box detector, either moment, `PASS_X`, `FEATURE_SETS_X` in `xr.py`; originals unchanged): coefficient +0.34 (90% interval 0.05 to 0.65) but out-of-fold log loss is unchanged at 0.5646 (0.5642 with it; replacing peak height loses accuracy: 0.5786). Peak height already carries almost the same information. Pipeline notebooks 07-12 re-run with it in `notebooks/box_either_xpass/`: calibration slope 1.02, AUC 0.77, split-half RoE 0.09 (-0.21 to 0.40), value over expected 0.27 (0.04 to 0.49), xR at release 0.50; intra-class correlation RoE 0.003, no shrunk interval excludes the league mean; percentile ranges 87-91 points wide. The conclusion is unchanged.
- **Z-scores** (notebook 15): hold-up level (RoE and duel are two-humped, EPV scores have long tails: skew 1.6 for value over expected) and striker level (shrunk estimate and 90% interval, standardised across the 21 rated strikers). The sd of the shrunk striker estimates is tiny against their intervals, so a 90% interval is 6 to 13 z-scores wide: z ranks the strikers on one scale but shows no difference that the data supports. z(set-up) vs z(duel) correlation +0.49; z(RoE) vs z(EPV over expected) +0.65.
- **Scenarios agreed** (tags per hold-up in `holdup_zscores_scenarios.csv`, rules in `scenario_thresholds.csv`): Difficult passes = lowest third of expected pass completion (<= 0.62; 173 hold-ups, 21% kept); High pressure = oval pressure >= 0.59 (172; 39% kept); Little support = no teammate with a 60%+ completion chance (45; 20% kept); Aerial balls (226; 21% kept). With about 8.6% of hold-ups, Little support gives only a handful per striker (6 each for the two shown), so scenario RoE there is a league-level read at best; a dot needs at least 5 hold-ups in the scenario.
- **Update to the scenarios**: Little support is now *at most one teammate with a 60%+ completion chance* (183 hold-ups, 35%; 28% kept; 14 strikers with 5 or more), replacing the none rule (45 hold-ups). Notebook 15 lists alternative rule sets with the share of hold-ups they cover (for example expected completion lowest quarter / third / 40%: 25 / 33 / 40%; oval pressure top half / third / quarter: 50 / 33 / 25%; 2+ / 3+ defenders within 5 m: 36 / 7%; at most 0 / 1 / 2 teammates at 60%+: 9 / 35 / 65%; no open lane 38%; aerial 43%).
- **Shrinkage within scenarios** (hierarchical model fitted inside each scenario; `scenario_shrunk.csv`): the real spread between strikers (largest plausible, 95th percentile) is 15.7 points for Difficult passes, 21.0 for High pressure, 14.1 for Little support, 13.8 for Aerial balls, against 7.7 overall; intra-class correlation 0.02, 0.05, 0.01, 0.02 (0.14, 0.18, 0.09, 0.11 at the largest plausible spread). Shrunk striker values with at least 5 hold-ups lie within -7 to +10 points of zero (raw -33 to +39), no 90% interval excludes the scenario league average, and the highest probability of being above it is 0.64 to 0.73. Example: Botić's raw -42 in High pressure on 3 hold-ups shrinks to -4.

## Final pipelines and datasets (consolidation)

- `event_id` = `<match_id>_<nnn>` (numbered by first contact within the match) is the key joining `data/events`, `data/features` and `data/model_results`. SkillCorner's own possession id is kept as `source_event_id`; it is not unique with the outcome (a received and a defender-first candidate can share it), which is why the old merges needed `(match_id, event_id, outcome)`.
- Events dataset: detection measurements, box geometry, outcome (`result`, `retained`) and EPV (`epv_before`, `epv_after`, `value_added`). Features dataset: the 13 model features (with raw `xpass_raw`), release-state versions and nothing else. Model results: `xpass` (calibrated), `xr_release`, `xr_contact`, `setup`, `setup_c`, `duel`, `roe`, `roe_c`, `exp_value`, `voe`.
- Out-of-fold results (`data/training/model_results_oof.csv`) are what the aggregation uses by default; scoring the training matches with the saved model is in-sample.
- Dropped from the final pipeline (still in `archive/`): the band detector, release-only and contact-only box modes, the pressing-intensity and exploratory pressure/support/pre-receipt columns, SkillCorner's and the flat-ball expected pass completion, and the press_* / goal-side columns of the detector.
- Player stats also carry `games` (matches played, from `playing_time` in the match files), `minutes`, `minutes_in_possession`, `holdups_per_game` and the per-90 rates; strikers with no hold-ups are not rows in the table.
- Scores per 90 minutes (`<score>_per90`, with `_lo`, `_hi`, `_p_above_league`, `_z_shrunk`): each draw of a striker's shrunk level per hold-up is multiplied by an independent draw of his hold-ups per 90 from the gamma-Poisson posterior (which uses his minutes played), so minutes enter the shrinkage through the rate. League reference = league mean level x league hold-up rate per 90.
- Scores per 90 minutes (`<score>_per90`, with `_lo`, `_hi`, `_p_above_league`, `_z_shrunk`): each draw of a striker's shrunk level per hold-up is multiplied by an independent draw of his hold-ups per 90 from the gamma-Poisson posterior (which uses his minutes played), so minutes enter the shrinkage through the rate. League reference = league mean level x league hold-up rate per 90.
