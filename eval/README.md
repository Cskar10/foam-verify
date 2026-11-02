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
