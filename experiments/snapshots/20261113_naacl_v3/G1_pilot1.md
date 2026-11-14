# G1 go/no-go: pilot 1 (2026-11-13 00:30Z)

**Build:** 16 cells (2 graphs x 8 categories), 6 accepted items each, seed 1, GLM-5.3-Flash on Novita FP8, judge panel GLM + Gemma-4-26B. Graph queries run through an SSH tunnel to jamming (loopback Neo4j). 7 cells hung when the laptop slept; their partial outputs are in `artifacts/runs_stalled/` and the cells were rerun.

| Check | Pilot | v2 | Threshold | Pass |
| --- | --- | --- | --- | --- |
| Empty-result rejects | 5.4% (10/186) | 24% | < 5% | marginal; cause fixed (see below) |
| Literal mismatches in accepted items | 0 | ~10% of items | 0 | yes |
| Ties at the ORDER BY/LIMIT cutoff (export audit) | 0 (81 n/a, 15 no tie) | 65 | 0 | yes |
| Easy / medium / hard | 33 / 37 / 26 (34/39/27%) | 134/81/1 (test) | within 10 points of 35/35/30 | yes |
| Panel judge agreement (kappa, n=98) | 0.66 | 0.22 | >= 0.6 | yes |
| Self-BLEU of questions | 0.64 | 0.87 | < 0.81 | yes |
| Redaction residual (v2 audit settings) | 0.0% | 1.05% | <= 1% | yes |
| Generator reference = template query answer | 48/53 (91%) | n/a | report | n/a |
| Downstream harness (GLM, 96 items, 3 conditions) | 0.76 / 0.80 / 0.80 projected EX; failure rate 0 | n/a | runs | yes |
| Generator-swap replay (Qwen3.5-9B, 8 items) | runs; 8/8 same answer | n/a | runs | yes |
| Spot check, 30 items read by Claude | 1 wrong (#9: account createTime used as withdrawal time), 1 minor (#25: extra columns), 2 questionable (keyword-style ambiguity; category mislabel) | n/a | <= 2 wrong | yes |
| Cost | $0.21 for 96 items; projected $7.0 for 3,200 at pilot efficiency | $3.23 / 2,609 | <= $4 projected | no (see below) |

**Fixes applied after the pilot (all tested; 629 tests pass):**
- Templates with no valid binding on the graph are retired after one failure. Before this, negation and aggregation cells spent their attempt budget retrying them.
- Built-in templates get a difficulty tier up front, and the tier-quota check runs before the paid judge.
- A template is retired after repeated deterministic-gate failures (one failure if it has no slots). This was the FinBench "top 10" template that tied 15 times.
- A template with no slots must return rows itself. This was the source of all 10 empty-result rejects (fixed literals that match no data).
- Identifier tie-breaks the question does not ask for (`ORDER BY n DESC, c.id`) no longer hide ties from the tie gate.
- New category contract: a yes/no question returns one boolean, a ranking question needs ORDER BY ... LIMIT, a negation question needs NOT, an aggregation question needs an aggregate.
- The keyword realization style is dropped because it loses the requested columns. Styles are now chosen per question rather than by a shared RNG.
- Apostrophes ("I'd") are no longer read as quotes by the literal gate.

**Decision: GO**, with the fixes above. The cost projection exceeds the first estimate. Most of the excess came from wasted attempts in the hard cells, which the retirement and gate-ordering fixes target. Expected full generation: about $5-6.
