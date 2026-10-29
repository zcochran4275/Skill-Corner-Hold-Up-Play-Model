# Hold-Up Play Model

Scores how well a forward holds the ball up with his back to goal, adjusted for how hard each situation was, and splits his retention into **set-up added** (movement before the pass) and **duel added** (winning the contact). Built on SkillCorner open tracking and event data.

## Documentation

| File | Contents |
| --- | --- |
| [docs/01_build_spec.md](docs/01_build_spec.md) | Full design spec: concepts, event definition, features, outcome, xR model, value added, outputs, visuals, pilot results |
| [docs/02_component_choices.md](docs/02_component_choices.md) | Decisions on data, pressure, EPV, support options and the hold-up definition (overrides the spec) |
| [docs/03_roadmap.md](docs/03_roadmap.md) | Build steps in order, as a checklist |

## Status

Design complete; build starting at roadmap step 1 (data loader).

## Data

SkillCorner open data (A-League 2024/25): https://github.com/SkillCorner/opendata. Raw data goes in `data/` and is not committed.
