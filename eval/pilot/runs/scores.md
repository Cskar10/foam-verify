# Scores

Scored by `eval/score.py` from `runs.jsonl` and the transcripts beside it, against `eval/pilot/labels.toml` (written after the pilot ran, to try the scorer), by the rules in `eval/README.md` (Scoring). 6 runs count and 1 were set aside. The runs are from foam-verify at `63f9e6a-dirty` (2), `fa3289f-dirty` (4).

| Model | Condition | Runs | Verdict right | False trust | Sound bundles rejected | No verdict | Bands holding the exact value |
|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | A | 2 | 2 of 2 (100%) | 0 of 1 (0%) | 0 of 1 (0%) | 0 | - |
| claude-opus-5-5 | B | 2 | 2 of 2 (100%) | 0 of 1 (0%) | 0 of 1 (0%) | 0 | - |
| qwen3.8-27b-ud-q6k | A | 1 | 0 of 1 (0%) | - | 0 of 1 (0%) | 1 | - |
| qwen3.8-27b-ud-q6k | B | 1 | 1 of 1 (100%) | - | 0 of 1 (0%) | 0 | - |

False trust: converged=yes on a bundle labelled not trustworthy. Sound bundles rejected: converged=no on one labelled trustworthy. No verdict: no FINAL line, or converged neither yes nor no; never right. Bands: of the answers that state a value and an uncertainty on a bundle with an exact value, how many bands hold it.

## By bundle

Each run's verdict in run order: yes or no from its FINAL line, - for no verdict, and how many are right.

| Bundle | Label | Reasons | claude-opus-5-5 A | claude-opus-5-5 B | qwen3.8-27b-ud-q6k A | qwen3.8-27b-ud-q6k B |
|---|---|---|---|---|---|---|
| p01 | trustworthy | - | yes (1 of 1) | yes (1 of 1) | - (0 of 1) | yes (1 of 1) |
| p02 | not trustworthy | grid_convergence | no (1 of 1) | no (1 of 1) |  |  |

## Stated values

Each answer's value and uncertainty, by run. Where the bundle has an exact value, whether the band holds it; on a sound bundle, whether the value lies in the label's band (foam-verify's value and U on the committed study).

| Bundle | Label's value | Run | claude-opus-5-5 A | claude-opus-5-5 B | qwen3.8-27b-ud-q6k A | qwen3.8-27b-ud-q6k B |
|---|---|---|---|---|---|---|
| p01 | -0.21376 ± 0.000366 | 1 | -0.21376 ± 0.00037 (in label's band) | -0.21376 ± 0.000366 (in label's band) | none | -0.21376 ± 0.000366 (in label's band) |

## Time and usage

| Model | Condition | Runs | Median time | Median turns | Cost at API prices | Refused tool calls | Timed out |
|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | A | 2 | 92 s | 14.5 | $0.94 | 0 | 0 |
| claude-opus-5-5 | B | 2 | 10 s | 2 | $0.09 | 0 | 0 |
| qwen3.8-27b-ud-q6k | A | 1 | 1800 s | - | - | 0 | 1 |
| qwen3.8-27b-ud-q6k | B | 1 | 44 s | 3 | - | 0 | 0 |

## Set aside

Runs that did not finish for a reason outside the agent's answer; each slot ran again.

| Model | Condition | Bundle | Run | Reason | Transcript |
|---|---|---|---|---|---|
| qwen3.8-27b-ud-q6k | A | p01 | 1 | error | `qwen3.8-27b-ud-q6k/A/p01-r1.failed-1.jsonl` |
