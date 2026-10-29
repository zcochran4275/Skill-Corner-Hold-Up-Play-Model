# Hold-Up Play Model: Build Spec

Exported from the live doc "Hold-Up Play Model: Build Spec" (28 Oct 2026). Decisions made after this spec are in `02_component_choices.md` and override it where they differ.

## Purpose

The model scores how well a striker holds the ball up, adjusted for how hard each situation was, and identifies which type of hold-up striker he is. It answers the recruitment question: when the ball goes into this striker with his back to goal, does he keep it more often than an average striker would in the same situations, how does he do it, and does it help the team?

The guiding principle is **credit the striker, not the service**. Raw retention mostly reflects the balls a striker is given (in the pilot, context alone moved retention by about 16 points), so every output is measured against an expectation for that exact situation.

This spec records the process and every decision made while designing it for the Tottenham recruitment analyst case study, so it can be built as a standalone project. A SkillCorner open-data pilot (20 A-League 2024/25 matches) proved the pipeline end to end; Part 2 of the case study used dummy model output.

## Core concepts

Good hold-up play has three qualities, there are two ways to be good at it, and the model tells them apart by splitting every hold-up into three moments.

**Three qualities**

1. **Ball retention:** when the ball is played into him with his back to goal, does his team still have it a few seconds later?
2. **Movement before the pass:** does he create separation and arrive on the ball with time, or let the defender get tight?
3. **Value added:** when he keeps it, does his release move the team forward, or only recycle it?

**Two types of hold-up striker**

- **The duel winner** deals with physicality: lets the defender come, shields, and wins the ball when it is tight. Suits long balls and crowded boxes.
- **The mover** avoids physicality: moves before the pass to lose his marker, receives with space and releases quickly. Suits a possession team with midfielders close by.

Both can keep the ball at the same rate, so a single retention number hides what recruitment needs to know.

**Three moments**

| Moment | Frame | Metric |
| --- | --- | --- |
| Pass release | The pass is played | xR at release: the odds he inherits |
| First contact | His first touch | Set-up added = xR at contact − xR at release |
| Outcome | 3 s after first touch | Duel added = kept − xR at contact |

Every moment is scored against an average striker in the same situation, so the service and the defence count neither for nor against him.

## Data requirements

The build needs synchronised tracking and event data for every player and the ball, plus a possession value model; body pose is optional.

| Input | What is used | Pilot source | Notes |
| --- | --- | --- | --- |
| Tracking | x, y of all 22 players per frame; ball x, y, z; possession group; period | SkillCorner broadcast tracking, 10 fps, extrapolated | Pitch-centred metres. Normalise so the striker's team attacks +x, using each goalkeeper's mean x per period |
| Events | Player possessions with frame start and end, start type (pass reception), end type (pass, possession loss, foul suffered, shot), pass outcome, player position (CF) | SkillCorner dynamic events | Links each reception to the passer's possession; frames must align with tracking |
| Context labels (validation) | Overall pressure, reception difficulty, passing option ease, 1–5 scales | SkillCorner dynamic events | Used to sanity-check own features, not as model inputs |
| Possession value | EPV before and after each action | SkillCorner EPV columns | Any club or provider EPV model works |
| Match metadata | Player ids, roles, team ids, pitch size, minutes | SkillCorner match JSON | Minutes give per-90 volume |
| Body pose (optional) | Torso orientation at first contact | SkillCorner pose, 2 matches only | Would replace the positional proxy for back to goal |

Access note from the pilot: the open-data tracking files are stored in Git LFS. A plain clone gives pointer stubs; the files download from `media.githubusercontent.com/media/SkillCorner/opendata/master/data/matches/<id>/<id>_tracking_extrapolated.jsonl` (about 90 MB each).

## Event definition

A hold-up is a pass reception by the striker who is posted on the opposition's last line when the pass is played, with a goalside defender engaged at first contact, in the attacking half.

**Linking frames**

1. Take every player possession by a centre forward whose start type is a pass reception.
2. The pass-release frame is the end frame of the previous possession by the same team, which must have ended in a pass. Skip it if the gap is more than 5 s (50 frames at 10 fps).
3. The first-contact frame is the striker's possession start frame.
4. Normalise both frames so the striker's team attacks +x.

**Gates**

| Gate | Rule | Checked at |
| --- | --- | --- |
| Posted on the last line | \|striker x − deepest outfield defender x\| ≤ 2.5 m (goalkeeper excluded) | Pass release |
| Defender engaged | Nearest goalside defender (defender x > striker x − 0.5 m) ≤ 3.5 m | First contact |
| Attacking half | Striker x > 0 | Pass release |
| Not a run in behind | Striker x − last line x ≤ 1.0 m | First contact |

**Decisions**

- **Check the line at pass release, not receipt.** Strikers often start on the shoulder and check short. In the pilot, 39 of 106 hold-ups (37%) would be missed by a receipt-time gate. It also avoids punishing the striker for a slow pass that lets the line step up.
- **No body orientation gate.** Pose data is not available at scale, so "back to goal" is inferred from being pinned on the last line with a goalside defender. Velocity direction was rejected as a proxy because it fails when the striker is stationary and posted. With pose data, orientation becomes a direct feature.
- **Aerial balls are included**, tagged as a subtype, because heading down is a different physical skill and matters for direct teams.
- **Dropping deep to link build-up is excluded** by the attacking-half and last-line gates.
- **Receptions beyond the line are excluded**: they are runs in behind, a different skill.
- Event count per team is itself a scouting signal (how often a striker gets into these situations).

## Difficulty factors

Four factors describe how hard each hold-up was; the first three are the situation he is given, the fourth is his own contribution before the ball arrives.

| Factor | Feature | Definition (pilot implementation) |
| --- | --- | --- |
| Pass difficulty | Pass distance | Ball position at release to striker at first contact, m |
| Pass difficulty | Ball speed | Pass distance ÷ flight time, m/s |
| Pass difficulty | Peak ball height | Max ball z during the flight, m |
| Pass difficulty | Aerial flag | Event high-pass flag, else peak height > 2 m |
| Pass difficulty | Pass angle | Angle of the pass vector off the attacking direction, degrees |
| Pass difficulty | Origin x | Where the pass was played from, normalised x |
| Defensive pressure | Separation at release / contact | Nearest outfield defender distance at each frame, m |
| Defensive pressure | Goalside defender distance | Nearest defender with x > striker x − 0.5 m, at first contact |
| Defensive pressure | Opponents within 3 m and 5 m | Counts at first contact |
| Defensive pressure | Closing speed (planned) | Nearest defender's velocity towards the striker |
| Defensive pressure | Pressure model (planned) | One continuous pressure value instead of several correlated distances |
| Support options | Teammates within 30 m | Count at first contact, goalkeeper excluded |
| Support options | Open options | Lane open when no opponent is within 2 m of the striker–teammate segment AND the teammate's nearest marker is > 3 m away |
| Support options | Mean option distance | Average distance to teammates within 30 m |
| Support options | Options moving towards him | Teammate velocity towards the striker > 1 m/s, from a 0.5 s window |
| Pre-receipt actions | Distance to last line at release | Striker x − last line x |
| Pre-receipt actions | Separation gain | Separation at contact − separation at release |
| Pre-receipt actions | Check-short distance | Striker x at release − striker x at contact |
| Pre-receipt actions | Speed at receipt | From a 0.5 s window, m/s |
| Context | Last-line height | Line position on the pitch, so a deep block and a high line are not treated alike |

**Decisions**

- **Let the model find the sign of speed at receipt.** Moving fast makes control harder but makes him harder to press.
- **Separation is measured twice** because the gap usually closes in flight (72% of pilot hold-ups, median 0.5 m).
- **Expect collinearity.** Separation and open options correlated at r = 0.45 in the pilot; one joint model handles it, so factors are never hand-weighted.
- **Planned extension:** summarise the on-ball window too (minimum separation, time with zero open options), because a first-contact snapshot understates situations that get harder while he holds it.

## Outcome definition

A hold-up succeeds if his team still has the ball 3 s after his first touch, whoever has it by then; a foul won counts as success.

| Outcome | Rule (pilot implementation) | Counts as |
| --- | --- | --- |
| Kept | No opponent possession starts within 30 frames of first contact | 1 |
| Foul won | End type foul suffered, or the next stoppage is a free kick for | 1, also reported as a style trait |
| Lost | End type possession loss, unsuccessful pass, or an opponent possession within 3 s | 0 |
| Own shot | The hold-up ends in his own shot (25 of 106 in the pilot) | Reported separately, not counted as kept |

**Decisions**

- **3-second window, deliberately short.** If his lay-off is perfect and the midfielder loses it two touches later, that is not his failure. A 3 to 5 s sensitivity check should confirm player rankings hold.
- **Time on the ball is a descriptor, never the target.** Holding for 4 s because nobody supports him is not better than a first-time lay-off.
- **Value is a separate output**, not part of this yes or no outcome (see Value added).

## Expected retention and the set-up / duel split

One model, expected retention (xR), gives the probability an average striker keeps a given ball; scoring it at two moments splits retention over expected into set-up added and duel added, which always sum exactly.

**The model**

- Target: the 0/1 outcome above. Features: the four difficulty factors.
- Baseline: gradient boosting, with a regularised logistic regression alongside for interpretability. Report calibration, not only AUC, because an over-confident model inflates every player's residuals.
- Training data: all league hold-up events. If too few, train on all attacking-half striker receptions with a hold-up flag as a feature (the pilot did this: 823 receptions).
- League and team context enter as features, so ratings are comparable across leagues.

**Two snapshots**

- **xR at release:** features known when the pass is played (pass difficulty, defenders and support at release, his position relative to the line). The odds he inherits.
- **xR at contact:** the same model on the first-contact state (separation, pressure and support at first touch). The odds after his movement.

```
Set-up added = xR_contact − xR_release
Duel added   = kept − xR_contact
RoE          = kept − xR_release = Set-up added + Duel added
```

Each is averaged over a player's hold-ups and scaled × 100, so units are retained balls per 100 hold-ups and zero is league average. Worked examples: an easy ball (xR 0.80) kept earns +0.20; a hard ball (xR 0.35) kept earns +0.65; the easy ball lost costs −0.80.

**How the types are identified**

- High set-up added, near-zero duel added → **the mover** (avoids contact).
- High duel added, near-zero set-up added → **the duel winner** (wins contact).
- Both high → complete.

**Decisions and refinement**

- **One joint model, never hand-weighted sub-scores**, because the factors overlap.
- **Credit pre-receipt movement once.** If his movement made the duel easier, xR at contact rises, so that credit sits in set-up added, not in the outcome.
- **Refinement to build:** part of the change between release and contact is teammates and defenders moving. The cleaner set-up added swaps only striker-controlled features (his separation gain, speed, distance to the line) for league-average values and measures the xR difference.

## Value added

Value added measures whether keeping the ball helped the team, because retention treats a safe backward lay-off the same as a bounce pass that springs a runner.

| Metric | Definition | Unit |
| --- | --- | --- |
| Value added | Change in EPV from first contact to the end of his action, plus at most one more action | EPV per hold-up |
| Expected value added | League-average value change for the same situation; the pilot binned by xR at contact (20 bins), production should model it on the same features | EPV per hold-up |
| Value over expected | (Value added − expected value added) × 100 | EPV per 100 hold-ups |
| Progressive release rate | Share of kept hold-ups whose release moves the ball forward or breaks a line | % |

**Decisions**

- **Cap the window at his action plus one more** so a teammate's mistake two touches later stays out of his number.
- **Compare players on a 2x2:** retention over expected (x) against value over expected (y). The four profiles are Complete (keeps it and moves the team forward), Wall (keeps it, plays safe), Risk-taker (loses it more but creates when it sticks), and Below par. Labels describe a type, not a verdict: a Wall can be exactly what a direct team wants.

## Situational splits

Retention over expected is also reported inside the league's hardest third of situations on each factor, which shows whether a striker gets better or worse as it gets harder.

1. Give every hold-up an ease score per factor (pass, pressure, support), low = hard.
2. Set the cut-off at the 33rd percentile of the league's events on that factor, so "hard" means the same thing for every striker.
3. For each player and factor, compute RoE within his hard events, and separately within the rest of his hold-ups.
4. Report the hard-situation RoE, the rest-of-his-hold-ups RoE, the event count, and his share of hard events (exposure).

**Why this controls for everything else:** xR already prices all four factors, so a striker's high-pressure number already accounts for how hard the pass and support were in those same events.

**Decisions**

- **Treat splits as tendencies.** In the dummy data each split held 17 to 34 events, giving intervals of about ±15 per 100.
- **Production version:** model player-specific difficulty effects inside the xR model (a hierarchical model with player random slopes on each factor), pulled towards the league average when samples are small. That gives every striker a stable "handles difficulty" rating instead of three noisy splits.
- Pressure and support ease are correlated (about 0.5 on the pitch), so a hard-pressure event is often a low-support one too; the xR adjustment handles it.

## Player outputs and uncertainty

Each striker gets five quality metrics and six style and context metrics, all with 90% intervals and league percentiles.

| Group | Metric | Question it answers | Unit |
| --- | --- | --- | --- |
| Quality | Retention over expected | Does he keep it more than the situation says he should? | Per 100 hold-ups |
| Quality | Set-up added | Does his movement make the job easier before the ball arrives? | Per 100 |
| Quality | Duel added | Does he win the situation he ends up in? | Per 100 |
| Quality | Value added | Does his retention make the team better off? | EPV per hold-up |
| Quality | Value over expected | Does he add more than the situation allows? | EPV per 100 |
| Style | Hold-ups per 90 | How often is he used, or gets himself used, this way? | Per 90 |
| Style | Aerial share and aerial RoE | Can he do it from long balls, not just passes into feet? | % and per 100 |
| Style | Progressive release rate | Does he play forward or recycle? | % |
| Style | Fouls won | Does he draw free kicks while shielding? | Per 100 |
| Style | Time on the ball | Quick lay-off, or shield and wait for support? | Median s |
| Situational | RoE on hard passes, high pressure, little support | Does he get better or worse as it gets harder? | Per 100 |

**Uncertainty**

- **Sample size:** about 2.7 hold-ups per team per match in the pilot, so roughly 80 to 100 a season for a first-choice striker. At 100 events, raw retention carries about ±10 points at 95%.
- **Intervals:** 90% bootstrap, resampling each player's own hold-ups 2,000 times. Hold-ups per 90 uses a Poisson interval on the count.
- **Percentile intervals:** the position of each resampled value among the other strikers' point estimates. This ignores the other players' own uncertainty, so it is slightly too narrow.
- **Shrinkage:** pull player ratings towards the league average in proportion to sample size (empirical Bayes or the hierarchical model), so a hot 30-event spell does not top the list.
- **Set-up added is far more precise than duel added** (in the dummy data, B's set-up interval was +6.0 to +7.4 while the duel intervals spanned about ±8). Set-up uses model probabilities on every event; duel depends on 0/1 outcomes.

Style rows describe a player; they do not rank him (a long time on the ball is not better).

## Visualisations

Four comparison charts were chosen, each answering one question, plus pitch graphics for explaining the method.

| Chart | Question | Design choices |
| --- | --- | --- |
| RoE vs value over expected scatter | Does keeping the ball help the team? | League in muted grey, dot size = number of hold-ups; targets as large dots with 90% interval crosses; quadrant labels name a type, not a verdict |
| Set-up added vs duel added scatter | Where does each player's retention come from? | Dashed diagonals = equal RoE, so position shows the source, not the total; interval crosses show set-up is precise and duel is noisy |
| Situational dot plot | Where does his retention hold up? | One row per situation; filled dot = hardest third, hollow ring = rest of his hold-ups; bars = 90% intervals; n shown per row |
| Head-to-head percentile bars | The full profile, with uncertainty | Mirrored bars (A left, B right) on league percentiles; white 90% whiskers; real value at the row end; dashed 50th-percentile line; quality above style |
| Set-up / duel waterfall | How one player's retention builds up | xR at release, then set-up, then xR at contact, then duel, then actual, per 100 hold-ups |
| Pitch frames and animation | How the factors are measured on a real event | Tracking frames per factor; a 0.6× speed clip with live readouts (separation, open options) and holds at release and first contact |

**Design rules**

- Two target colours only, checked for colour-blind separation against the dark background: blue #1F9BD6 and orange #D9761F. League context in muted #3A4E80. On the pitch: striker cyan, his team white, defenders coral, ball yellow; open lanes solid green, blocked lanes dashed coral.
- Percentiles let metrics with different units share one axis; real values are always printed beside them.
- No radar charts: the shape depends on axis order and the area exaggerates differences.
- Show intervals by default; about 80 hold-ups a season is not many.
- Exported decks drop embedded video: PowerPoint needs the clip embedded separately (done with python-pptx `add_movie`).

## Pilot results (SkillCorner open data)

The pipeline ran end to end on 20 A-League 2024/25 matches and found 106 hold-ups from 1,085 striker receptions; the model itself was weak at this sample size.

Detection funnel: 1,085 striker pass receptions, 823 in the attacking half, 198 posted on the last line at release, 106 with an engaged defender (none were runs in behind once the other gates applied).

| Finding | Value | Base |
| --- | --- | --- |
| Hold-ups per team per match | About 2.7 | 106 events, 40 team-matches |
| Strikers with at least one hold-up | 35, max 12 events each | 106 events |
| Retention, hold-ups vs other striker receptions | 60% vs 66% | 106 vs 979 |
| Hold-ups missed by a receipt-time gate | 39 of 106 (37%) | Hold-ups |
| Retention, ground vs aerial passes | 69% vs 53% | 707 vs 116 attacking-half receptions |
| Retention by open options: none, one, two or more | 57%, 61%, 73% | 237, 132, 454 receptions |
| Defender closes the gap during the flight | 72% of hold-ups, median 0.5 m | Hold-ups |
| Labelled high or very high pressure by SkillCorner | 88 of 98 labelled | Hold-ups |
| Hold-ups ending in his own shot | 25 of 106 | Hold-ups |
| Fouls won | 7 of 106 | Hold-ups |
| Correlation, separation vs open options | r = 0.45 | Attacking-half receptions |
| Pilot logistic xR model, 5-fold cross-validated AUC | 0.59 | 823 attacking-half receptions, 11 features |

Showcase events used in the deck: L. Jovanovic, Adelaide United v Brisbane (match 1874553, event 8_447: posted 2.0 m short of the line, defender 3.1 m at contact, 3 of 9 options open, laid off at 2.7 s); G. May, Auckland (1899585, 8_101: on the line at release, 9.0 m short at receipt); B. Fornaroli, Melbourne Victory (1959846, 8_733: separation 1.7 m to 3.2 m); M. Mata flick-on (1996436, 8_44: peak ball height 11.8 m).

## Limits, open questions and build roadmap

The biggest risks are small samples and a model trained on too little data; the roadmap builds the pipeline first, then the model, then the outputs.

**Known limits**

- One season per player gives wide intervals; situational splits especially are tendencies.
- The pilot model was weak (AUC 0.59) on 20 broadcast-tracked matches.
- Direct teams create more hold-ups and leagues differ in physicality, so rate and volume must be shown together and leagues adjusted for.
- Back to goal is inferred from position without pose data.
- The metric screens and describes; it does not replace watching the player.

**Open questions**

- Should a hold-up that ends in his own shot count as kept, or stay a separate outcome?
- Are 2.5 m (last line) and 3.5 m (engaged defender) the right thresholds? Test 1.5 to 3.5 m and 2.5 to 5 m.
- Is 3 s the right window? Test 3, 4 and 5 s for ranking stability.
- Which EPV model, and does capping at his action plus one hold up?
- Simple set-up added (all change) or striker-controlled counterfactual?

The roadmap is maintained in `03_roadmap.md`.
