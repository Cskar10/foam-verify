# Scores

Scored by `eval/score.py` from `runs.jsonl` and the transcripts beside it, against `eval/labels.toml` (sha256 `0b5fbcccc570`, the labels committed at `90d5c4f`), by the rules in `eval/README.md` (Scoring). 72 runs count and 0 were set aside. The runs are from foam-verify at `5239b11` (72).

| Model | Condition | Runs | Verdict right | False trust | Sound bundles rejected | No verdict | Bands holding the exact value |
|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | A | 36 | 29 of 36 (81%) | 7 of 24 (29%) | 0 of 12 (0%) | 0 | 12 of 12 |
| claude-opus-5-5 | B | 36 | 36 of 36 (100%) | 0 of 24 (0%) | 0 of 12 (0%) | 0 | 7 of 7 |

False trust: converged=yes on a bundle labelled not trustworthy. Sound bundles rejected: converged=no on one labelled trustworthy. No verdict: no FINAL line, or converged neither yes nor no; never right. Bands: of the answers that state a value and an uncertainty on a bundle with an exact value, how many bands hold it.

## By bundle

Each run's verdict in run order: yes or no from its FINAL line, - for no verdict, and how many are right.

| Bundle | Label | Reasons | claude-opus-5-5 A | claude-opus-5-5 B |
|---|---|---|---|---|
| b01 | not trustworthy | iterative | no no no (3 of 3) | no no no (3 of 3) |
| b02 | not trustworthy | two_grids | yes yes yes (0 of 3) | no no no (3 of 3) |
| b03 | not trustworthy | refinement_ratio | yes yes yes (0 of 3) | no no no (3 of 3) |
| b04 | not trustworthy | grid_convergence | no no no (3 of 3) | no no no (3 of 3) |
| b05 | not trustworthy | settings | no yes no (2 of 3) | no no no (3 of 3) |
| b06 | trustworthy | - | yes yes yes (3 of 3) | yes yes yes (3 of 3) |
| b07 | trustworthy | - | yes yes yes (3 of 3) | yes yes yes (3 of 3) |
| b08 | not trustworthy | grid_convergence | no no no (3 of 3) | no no no (3 of 3) |
| b09 | trustworthy | - | yes yes yes (3 of 3) | yes yes yes (3 of 3) |
| b10 | not trustworthy | iterative | no no no (3 of 3) | no no no (3 of 3) |
| b11 | trustworthy | - | yes yes yes (3 of 3) | yes yes yes (3 of 3) |
| b12 | not trustworthy | iterative, grid_convergence | no no no (3 of 3) | no no no (3 of 3) |

## Stated values

Each answer's value and uncertainty, by run. Where the bundle has an exact value, whether the band holds it; on a sound bundle, whether the value lies in the label's band (foam-verify's value and U on the committed study).

| Bundle | Label's value | Run | claude-opus-5-5 A | claude-opus-5-5 B |
|---|---|---|---|---|
| b02 | exact 56.9083 | 1 | 56.8997 ± 0.0257 (holds exact) | 56.8997 ± 0.0257 (holds exact) |
| b02 | exact 56.9083 | 2 | 56.8997 ± 0.026 (holds exact) | 56.8997 |
| b02 | exact 56.9083 | 3 | 56.8997 ± 0.026 (holds exact) | 56.8997 |
| b03 | exact 56.9083 | 1 | 56.8997 ± 0.011 (holds exact) | none |
| b03 | exact 56.9083 | 2 | 56.8997 ± 0.0107 (holds exact) | none |
| b03 | exact 56.9083 | 3 | 56.8997 ± 0.011 (holds exact) | 56.8997 |
| b06 | 56.8997 ± 0.0108; exact 56.9083 | 1 | 56.9 ± 0.011 (holds exact, in label's band) | 56.8997 ± 0.0108 (holds exact, in label's band) |
| b06 | 56.8997 ± 0.0108; exact 56.9083 | 2 | 56.8997 ± 0.011 (holds exact, in label's band) | 56.8997 ± 0.0108 (holds exact, in label's band) |
| b06 | 56.8997 ± 0.0108; exact 56.9083 | 3 | 56.8997 ± 0.011 (holds exact, in label's band) | 56.8997 ± 0.0108 (holds exact, in label's band) |
| b07 | -0.208892 ± 0.000328 | 1 | -0.20889 ± 0.00033 (in label's band) | -0.208892 ± 0.000328 (in label's band) |
| b07 | -0.208892 ± 0.000328 | 2 | -0.208892 ± 0.00033 (in label's band) | -0.208892 ± 0.000328 (in label's band) |
| b07 | -0.208892 ± 0.000328 | 3 | -0.208892 ± 0.00033 (in label's band) | -0.208892 ± 0.000328 (in label's band) |
| b09 | 0.179365 ± 0.000257 | 1 | 0.17936 ± 0.00026 (in label's band) | 0.179365 ± 0.000257 (in label's band) |
| b09 | 0.179365 ± 0.000257 | 2 | 0.17936 ± 0.00026 (in label's band) | 0.179365 ± 0.000257 (in label's band) |
| b09 | 0.179365 ± 0.000257 | 3 | 0.17936 ± 0.00026 (in label's band) | 0.179365 ± 0.000257 (in label's band) |
| b11 | 56.8997 ± 0.0108; exact 56.9083 | 1 | 56.9 ± 0.011 (holds exact, in label's band) | 56.8997 ± 0.0108 (holds exact, in label's band) |
| b11 | 56.8997 ± 0.0108; exact 56.9083 | 2 | 56.8997 ± 0.011 (holds exact, in label's band) | 56.8997 ± 0.0108 (holds exact, in label's band) |
| b11 | 56.8997 ± 0.0108; exact 56.9083 | 3 | 56.8997 ± 0.0108 (holds exact, in label's band) | 56.8997 ± 0.0108 (holds exact, in label's band) |

## Time and usage

| Model | Condition | Runs | Median time | Median turns | Cost at API prices | Refused tool calls | Timed out |
|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | A | 36 | 46 s | 16.5 | $12.65 | 0 | 0 |
| claude-opus-5-5 | B | 36 | 17 s | 3 | $2.24 | 0 | 0 |
