# Retail Rivals AI

This repository is Retail Rivals plus the rival, shopper, supplier, town, and advisor minds.

The game lives in `retail_rivals/open_late`. The minds are `retail_rivals/open_late/ai`. Look-ahead reads the game's factor card and market costs (opening cost, factor 95, factor 88 rent). It does not fork the weekly engine. A rival door costs supercenter money: the city's market cost scaled so Seattle is $30 million before factor 95, paid from cash. Occupancy is the rent slice of operating expense, not a second lease. Cost of goods is locked at the personality's shelf, and a move that earns less than standing still gets no share credit. `open_late/standin` steps those actions so the minds can be tested on their own. A Sunday caller can take the actions `RetailAI` returns and apply them.

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
