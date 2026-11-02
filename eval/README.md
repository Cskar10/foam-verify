# Agent evaluation: bundles and labels

Does an AI agent judge a CFD grid study better with foam-verify's MCP tools than with the files
alone? Each agent gets one bundle and one question:

> Is the reported value of `<qoi>` converged and mesh-independent? Give the value with its
> uncertainty, or say why you can't.

- **Condition A:** the agent may read every file in the bundle, logs and `postProcessing/`
  included, and nothing else.
- **Condition B:** the same, plus the foam-verify MCP server with the bundle as its root
  ([docs/mcp.md](../docs/mcp.md)).

The measures are the false-trust rate (the agent calls a value trustworthy that the label says is
not), the verdict accuracy, and on the duct bundles whether a stated band contains the exact
value. With twelve bundles every rate is given with its counts. The runs and the scoring are
week 4's; this folder holds what they need.

## Labels first

[`labels.toml`](labels.toml) gives the expected verdict on every bundle, why, and the reasons an
answer may name. It was written and committed before any bundle was built and before any agent
saw one, and it does not change afterwards: the project log records the commit. The labels rest
on evidence outside the bundles: the committed studies and their reports, the exact f Re of the
duct, Marchi, Suero and Araki's (2009) cavity values, and the committed runs' histories, which
predict what a run stopped early holds. If a bundle turns out not to show what its label says,
the bundle is rebuilt, not the label.

Four bundles are sound and eight are not; their numbers are shuffled, so a number says nothing
about a bundle.

## Bundles

`bundles/b01` to `bundles/b12`, each a grid study as foam-verify reads it: `study.toml` with the
one QoI asked about, and one OpenFOAM case per level with its inputs, mesh header, logs and
function-object output. A bundle holds nothing that gives the answer away: no report, no
README, no reference values (the duct's exact f Re among them), no comments that say what is
wrong, and neutral names. Seven are cut from the committed studies under `studies/`; five need
new runs in the pinned container (`studies/README.md`), made by
[`generate.py`](generate.py) and [`run.sh`](run.sh).

## Building and checking

```console
$ python3 eval/generate.py setup
$ podman run --rm -v "$PWD":/work:z -w /work --entrypoint /bin/bash $IMG eval/run.sh
$ python3 eval/generate.py collect
```

`$IMG` is the pinned image in `studies/README.md`. The new runs take about 7.5 minutes on 24
cores. `eval/build/`, the full cases, is not committed.

[`tests/test_eval.py`](../tests/test_eval.py) checks every built bundle against its label from
its files and the committed studies, not from foam-verify: a run stopped early reproduces the
committed run's values up to its stop, sample for sample; a changed setting is the only
difference from the committed case; the refinement ratios and cell counts are what the label
says. It also checks that no bundle holds a report, a README or a telling comment. Last, it
records foam-verify's own verdict on each bundle: it must match the label, failing a check that
finds the label's main reason.

## As built

All twelve bundles were built on 2 Nov 2026, after the labels, from the studies committed at
`db88676`; `generate.py collect` rebuilds them byte for byte. Two labels quote a number that the
built bundle does not match exactly. Both labels stay as committed; their verdicts and reasons
are unaffected:

- **b12**: the label quotes values predicted from the committed runs' residuals, sampled every
  10 iterations, at iterations 280, 440, 820 and 1430. The runs stopped at 279, 440, 811 and
  1419. There dp changes by 6.8 to 22% of its settled value over the last 50 iterations (the
  label says 7 to 23%) and lies up to 12.6% from it (the label says 15%).
- **b04**: the label says the loss changes by 0.556 from 12k to 28k, the difference of the
  rounded values in `studies/pitzDaily/README.md`; the values themselves give 0.5555. R = 1.08
  either way.

Also:

- **The cavity bundles** read their point QoIs from `postProcessing/ghiaPoints`, the name the
  committed runs gave those probes. An agent may compare the values with Ghia et al.'s (1982)
  from memory, and those differ from the converged solution by 1.3 to 2.1% at all three points
  (`studies/cavity/README.md`). The name is the same in both conditions.
- foam-verify's own verdict matches the label on all twelve bundles. The four sound bundles are
  clean passes, with bands that hold the exact f Re or Marchi et al.'s value; each of the eight
  others fails the check that finds its label's main reason. Alone, the tool trusts none of the
  broken bundles.
