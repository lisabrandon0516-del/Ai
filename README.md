# Retail Rivals AI

This repository is the rival, shopper, supplier, town, and advisor logic for Retail Rivals.

The corporate sim is not here. Nothing in this tree reads or patches that game. `open_late/ai` is the minds. `open_late/standin` is a small deterministic world so those minds can be stepped and tested on their own. When the game exists, it can call `RetailAI` and apply the actions itself.

A CEO scores a move on the same city logit the Sunday shopper card uses. Dollar sales are that traffic times the shelf price. The score is the belief-weighted average of four player replies (price fighter, premium, expander, passive). Big calls then take one seeded reply and the best follow-up. `tools/tune_personalities.py` rescores weight nudges on that stand-in.

There is no network call and no language model. Random draws come from `ai_rng` (blake2b of the save seed, stream, week, and keys). Difficulty `off`, or a save with AI disabled, draws nothing and leaves multipliers at 1.0.

Section 9 of the master spec is locked to the recommended defaults:

- This package owns the shopper model.
- `off` / `calm` / `standard` / `stern` also scale how many chains act and how many search iterations run.
- Towns delay a permit by 2–8 weeks and do not deny it.
- The advisor recommends and jumps to an existing desk. It does not place orders.
- Personalities ship as hash-checked JSON.

```bash
pip install -e ".[dev]"
pytest
```

`tools/ai_harness.py` runs a four-week smoke grid. `tools/tune_personalities.py` is an offline weight probe and is not part of the default tests.
