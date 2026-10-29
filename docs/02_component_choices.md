# Component choices

Decisions made on 28 Oct 2026, after researching open-source options. These override `01_build_spec.md` where they differ. The live version is the "Component choices" tab of the Hold-Up Play Model doc.

## Decision log

| Area | Decision | Replaces in spec |
| --- | --- | --- |
| Training data | SkillCorner open data only for now; revisit pooling if xR stays weak | — |
| Pressure | Build both pressing intensity and the pressure oval; keep the one with better cross-validated xR log loss and stronger rank correlation with SkillCorner pressure labels | "Pressure model (planned)", "Closing speed (planned)" |
| Value | SkillCorner EPV for headline metrics, plus an open location-based EPV grid as a robustness check | "Which EPV model" open question |
| Support options | Geometric lanes (spec) + "teammate is free" from the pressing-intensity matrix + a physics-based expected-pass-completion threshold (test 60%, 70%, 80%) | Open options feature |
| xPass model | Physics-based (Spearman-style interception model), no training | — |
| Hold-up scope | Open play only; any advanced forward, not only CF; counted whenever he gets the first touch, even if he never controls it; back to goal from the spec gates only | "centre forward" in linking step 1 |
| Last line | Back-line algorithm with a band (below) | Deepest outfield defender, 2.5 m |
| Defender engaged | 3.5 m goal-side for the first build; test a pressure-model threshold later | — |

## Back-line algorithm

1. At pass release, sort the defending team's outfield players by depth (normalised x, deepest first).
2. Start the line at the second-deepest player, so one covering defender cannot set it alone.
3. Add any defender within 5 m in x of a player already in the line, including the deepest one; repeat until no one else joins.
4. Stop adding players more than 15 m in x from the starting player.
5. Line height = x of the line's members (deepest member or median, to test).
6. The striker is on the last line if he is within a band of about ±10 m of the line height.

Sensitivity check: ±10 m is much wider than the spec's 2.5 m and will admit receptions in front of a deep block. Test bands of 2.5, 5 and 10 m and review clips from each. The "not a run in behind" gate still applies on the far side of the line.

## First-touch rule

- Include the ball when he gets the first touch; exclude it when a defender touches it first.
- A scuffed touch or flick that is lost counts as lost.
- Check whether SkillCorner logs these as player possessions. If not, detect first touch from tracking (ball within reach of him before any defender).

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
| SkillCorner open data | A-League 2024/25, 10 fps, dynamic events with EPV and pressure labels; MIT. README lists 10 matches; the spec says 20 (check) |
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
