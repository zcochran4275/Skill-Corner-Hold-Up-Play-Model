# Component choices

Decisions made on 28 Oct 2026, after researching open-source options. These override `01_build_spec.md` where they differ. The live version is the "Component choices" tab of the Hold-Up Play Model doc.

## Decision log

| Area | Decision | Replaces in spec |
| --- | --- | --- |
| Training data | SkillCorner open data only for now; revisit pooling if xR stays weak | — |
| Pressure | Built both (28 Oct 2026), re-evaluated 29 Oct after the engaged gate was dropped. The pressure oval beats pressing intensity on SkillCorner label correlation (0.72 vs 0.55) and cross-validated fit, but plain distances (defenders within 5 m, nearest defender) do better than either. Feed distance features and the oval into the xR model and let regularisation decide; keep pressing intensity in the code as an option. Its parameters are unstable (0.19-0.63) and broadcast velocities are noisy. | "Pressure model (planned)", "Closing speed (planned)" |
| Value | SkillCorner EPV for headline metrics, plus an open location-based EPV grid as a robustness check | "Which EPV model" open question |
| Support options | Geometric lanes (spec) + "teammate is free" from the pressing-intensity matrix + a physics-based expected-pass-completion threshold (test 60%, 70%, 80%) | Open options feature | Built 29 Oct 2026: all three views computed; options at 60%+ completion and the sum of expected completions help most, so the xR model gets those plus open lanes and lets regularisation decide. The pass-completion constants (14 m/s, 0.5 s, 7 m/s) are hand-set and sensitive.
| xPass model | Physics-based (Spearman-style interception model), no training | — |
| Hold-up scope | Any advanced forward (CF/LF/RF), not only CF; restarts (goal kicks, throw-ins, free kicks, corners) included and labelled; a pass won by the defender first counts as a failed hold-up; new gate: the ball must travel towards goal (within 45 degrees), not arrive from the side; the attacking-half gate is optional and off by default (a forward only has to be on the back line). Changed 28 Oct 2026 from "open play only". | "centre forward" in linking step 1 |
| Last line | Back-line algorithm with a band (below) | Deepest outfield defender, 2.5 m |
| Defender engaged | Not a detection rule (29 Oct 2026): being posted on the back line at release is enough, and how well he gets away from defenders is assessed afterwards from separation and pressure features. The old gate (a defender behind him within 3.5 m, or reaching him within 1 s from tracking velocity) stays in the code behind `require_engaged`, off by default. | Spec gate 2 (defender engaged) |

## Back-line algorithm

1. At pass release, sort the defending team's outfield players by depth (normalised x, deepest first).
2. Start the line at the second-deepest player, so one covering defender cannot set it alone.
3. Add any defender within 5 m in x of a player already in the line, including the deepest one; repeat until no one else joins.
4. Stop adding players more than 15 m in x from the starting player.
5. Line height = x of the line's members (deepest member or median, to test).
6. The striker is on the last line if he is within a band of about ±10 m of the line height.

Sensitivity check: ±10 m is much wider than the spec's 2.5 m and will admit receptions in front of a deep block. Test bands of 2.5, 5 and 10 m and review clips from each. The "not a run in behind" gate still applies on the far side of the line.

## First-touch rule

- A pass where the defender touches it first is kept as a failed hold-up (outcome `defender_first`).
- A scuffed touch or flick that is lost counts as lost.
- Resolved: SkillCorner logs the opponent interception, so the failure is found from the unsuccessful pass targeting him plus the next opponent `pass_interception`. Scuffed touches he still controls are not separately detected.

## Options considered

### Pressure

| Option | How it works | Strengths | Weaknesses |
| --- | --- | --- | --- |
| Pressing intensity (Bekkers 2025, unravelsports) | Time for each defender to reach the striker from positions and velocities (0.7 s reaction), turned into a probability of getting there within 1.5 s (σ = 0.45) | Captures closing speed; loads SkillCorner through kloppy; gives pressure on every teammate too | No quantitative validation in the paper; unbounded pitch ignores touchlines; noisy velocities on extrapolated broadcast players |
| Pressure oval (Andrienko 2017, Herold 2022; databallpy) | Each opponent in an oval around the striker adds (1 − d/L)^1.75; 9 m on the goal side, 3 m behind | Simple, interpretable; goal-side defender weighted most; ~30 lines to implement | Distance and angle only; hand-set constants |
| SkillCorner labels | overall_pressure, time_to_impact, space_constraint, reception_difficulty, 1–5 | Ready made | Categorical; method unpublished; SkillCorner only; possession start/end, not pass release |

Labels stay as validation only.

### Value (EPV)

| Option | Strengths | Weaknesses |
| --- | --- | --- |
| SkillCorner EPV (possession_epv_for_start/_end, pass_reception_epv_for, pass_epv_delta_for; 30 s or next stoppage horizon) | Already aligned to our events; full tracking context | Method and validation unpublished; SkillCorner only |
| Static EPV grid (Shaw, Friends of Tracking) | Any provider; trivial | Ignores players; licence to check |
| xT / VAEP (socceraction, MIT) | Trainable on any event data | Not actively developed (1.5.3, Aug 2024); no SkillCorner converter |
| Own tracking EPV (Fernández 2021; OJN-EPV 2025) | Best in class | A project in itself; needs far more data |

### Training data

| Dataset | Notes |
| --- | --- |
| SkillCorner open data | A-League 2024/25, 10 fps, dynamic events with EPV and pressure labels; MIT. The repo README says 10 matches but the folder holds 20 (confirmed 28 Oct 2026) |
| Gradient Sports (PFF FC) World Cup 2022 | 64 matches, tracking + events; request form; terms not stated |
| IDSSE / DFL | 7 Bundesliga matches, 25 fps, CC-BY 4.0 |

## Sources

- Pressing Intensity, Bekkers 2025: https://arxiv.org/abs/2501.04712
- unravelsports models: https://unravelsports.readthedocs.io/en/latest/api/soccer/models.html
- databallpy pressure: https://databallpy.readthedocs.io/en/main/features/pressure_page.html
- SkillCorner open data: https://github.com/SkillCorner/opendata
- SkillCorner pressure metrics: https://skillcorner.com/articles/introducing-skillcorners-new-pressure-metrics
- SkillCorner EPV: https://skillcorner.com/articles/introducing-skillcorners-expected-possession-value-epv
- kloppy: https://github.com/PySport/kloppy
- socceraction: https://pypi.org/project/socceraction/
- OJN-EPV, Overmeer et al. 2025: https://arxiv.org/html/2502.02565v1
- Gradient Sports World Cup 2022: https://www.gradientsports.com/blog/pff-fc-release-2022-world-cup-data
- IDSSE / DFL open data: https://huggingface.co/datasets/pysport/idsse-data/blob/main/README.md
- CMU pressing study: https://www.stat.cmu.edu/cmsac/sure/2025/showcase/soccer_tracking/report.html
- Pitch to the Pros (SkillCorner passing options): https://ringhilterra.github.io/projects/pitch-to-pros-3/
