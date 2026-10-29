# Build roadmap

Steps in build order, with the decisions from `02_component_choices.md` folded in. Tick items as they land.

## Phase 1: Data and events

- [ ] **1. Data loader.** Download SkillCorner open-data tracking (Git LFS, ~90 MB per match via media.githubusercontent.com), dynamic events and match metadata. Normalise so the attacking team plays +x per period (goalkeeper mean x). Confirm match count (README says 10, spec says 20) and the passing-option and EPV column names.
- [ ] **2. Back-line algorithm.** Second-deepest outfield defender as seed, chain-add within 5 m, 15 m cap, line height (deepest member vs median).
- [ ] **3. Hold-up detector.** Open play only; any advanced forward; pass release frame from the previous team possession ending in a pass (≤ 5 s gap); first touch by him (detect from tracking if SkillCorner has no possession); gates: on the line within the band, defender goal-side within 3.5 m, attacking half, not beyond the line.
- [ ] **4. Sensitivity report.** Band 2.5 / 5 / 10 m; engaged defender 2.5–5 m; event counts and clip review per setting.
- [ ] **5. Outcome labeller.** Kept, foul won, lost (including lost first touches), own shot; 3 s window with a 3–5 s check.

## Phase 2: Features

- [ ] **6. Pass difficulty.** Distance, ball speed, peak height, aerial flag, angle, origin x.
- [ ] **7. Pressure models.** Pressing intensity (unravelsports or own implementation) and pressure oval, at release and first contact.
- [ ] **8. Support options.** Geometric lanes, teammate-is-free from the pressure matrix, physics-based xPass per teammate with 60/70/80% thresholds.
- [ ] **9. Pre-receipt actions and context.** Distance to line, separation gain, check-short, speed at receipt, last-line height.
- [ ] **10. Validate features** against SkillCorner pressure, reception difficulty and passing-option-ease labels; pick the pressure model.

## Phase 3: Model

- [ ] **11. Train xR.** Gradient boosting + regularised logistic; cross-validated by match; calibration plot; train on all attacking-half forward receptions with a hold-up flag if hold-ups are too few.
- [ ] **12. RoE, set-up added, duel added.** Then the striker-controlled counterfactual for set-up added.
- [ ] **13. Value added.** SkillCorner EPV over his action plus one; expected value added; value over expected; repeat with the open EPV grid and compare rankings.

## Phase 4: Player outputs

- [ ] **14. Situational splits**, then a hierarchical model with player difficulty slopes.
- [ ] **15. Uncertainty.** Bootstrap 90% intervals (2,000 resamples), Poisson for per-90, shrinkage, league percentiles.
- [ ] **16. Player scorecard and charts.** RoE vs value scatter, set-up vs duel scatter, situational dot plot, head-to-head percentile bars, waterfall, pitch frames.

## Later

- [ ] On-ball window features (minimum separation, time with zero options)
- [ ] Pose-based orientation where pose data exists
- [ ] Pool more data (Gradient/PFF, IDSSE) and league adjustment
