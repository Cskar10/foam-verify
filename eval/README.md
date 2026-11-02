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

## Running the agents

[`run_agents.py`](run_agents.py) runs Claude Code headless (`claude -p`) on each bundle, in each
condition, and saves every transcript:

```console
$ uv run --extra mcp python eval/run_agents.py --bundles b01 b02 --runs 3   # eval/runs/
$ uv run --extra mcp python eval/run_agents.py --pilot                      # eval/pilot/runs/
$ uv run --extra mcp python eval/run_agents.py --probe                      # the isolation check
```

The question every agent gets, with the QoI filled in:

```text
The current folder holds a CFD grid study: study.toml describes it, and each grid level's OpenFOAM
case is in its own subfolder.

Is the reported value of <qoi> converged and mesh-independent? Give the value with its
uncertainty, or say why you can't.

End your answer with this line, filled in:
FINAL: converged=<yes|no>; value=<number|none>; uncertainty=<number|none>
value is the reported value of <qoi>; uncertainty is its 95% uncertainty U, such that the
mesh-independent value lies within value +/- U. converged=yes means that the value is converged
and mesh-independent.
```

The question is the plan's; the last line is added so that a script can score every answer the
same way, in both conditions.

Each run is isolated three ways:

- **A sandbox.** The agent runs inside bubblewrap, in Linux namespaces that hold only the system's
  `/usr` and `/etc`, an empty `/tmp`, its own `/proc`, a fresh copy of the bundle read-only at
  `/study` (its working folder), and under `/home` only what the run needs: the Claude Code
  binary, the login file read-only, and in condition B foam-verify's code and Python. The labels,
  the committed studies, earlier runs and everything else on the machine are not in it.
- **Its tools.** Read, Glob and Grep only (no shell, no writing, no web), in Claude Code's
  `dontAsk` permission mode, with every read under `/home` and `/proc` refused, which keeps the
  login file out of reach. In condition B foam-verify's server has `/study` as its only root.
- **No user setup.** No user settings (so no hooks or plugins), no `CLAUDE.md` or auto-memory, no
  skills or slash commands, no MCP server but foam-verify's, and an environment built from
  scratch.

Every run appends a line to `runs.jsonl` beside the transcripts: the bundle, condition, model and
foam-verify commit, the time taken, the turns, the token usage and its cost at API prices, whether
the bundle copy was unchanged, and the answer's FINAL line. The script never reads the labels. A
run that fails, times out or hits the usage limit stops the batch, and so does a login token close
to expiry, so that no token is refreshed inside a sandbox; started again, a batch skips the runs
it has. Scored runs only start from committed code, so the commit each one records is the code it
ran; the pilot ran from the working tree, which its index marks `-dirty`.

**The isolation probe** (2 Nov 2026, Claude Code 2.1.312, Opus 5.5) gave condition B's sandbox a
list of ways out and planted a canary file beside the login file. Reading the labels' path, the
canary or `/proc/1/environ`, and grepping the home folder, were refused. A grep for the canary's
text from `/` and a glob for its name from `/` found nothing, `/tmp` was empty, and foam-verify's
server refused a study outside `/study`. The agent had no instructions from any `CLAUDE.md`,
`AGENTS.md` or memory file. An earlier probe without the sandbox found that Claude Code's
permission rules alone leave `/tmp` readable, where test runs leave copies of the committed
studies with their reports; hence the sandbox. The probe's transcripts name paths in the home
folder and are not committed.

## Pilot

Two pilot bundles try the harness before any scored run: `pilot/bundles/p01` (the cavity's u_min
on all four levels, sound) and `p02` (pitzDaily's reattachment length on all four levels, which
does not converge). Their QoIs are ones no evaluation bundle asks about, and they are not part of
the evaluation. One run of each, in each condition, on Claude Opus 5.5 (`claude-opus-5-5`), 2 Nov
2026; transcripts and index in [`pilot/runs/`](pilot/runs/):

| Bundle | Condition | Time | Turns | Tokens read (cached) | Written | Cost at API prices | FINAL |
|---|---|---|---|---|---|---|---|
| p01 | A | 102 s | 16 | 212,036 (+46,225 new) | 5,747 | $0.53 | converged=yes; -0.21376 +/- 0.00037 |
| p01 | B | 9.5 s | 2 | 11,836 (+3,425 new) | 818 | $0.05 | converged=yes; -0.21376 +/- 0.000366 |
| p02 | A | 83 s | 13 | 200,171 (+33,656 new) | 5,056 | $0.41 | converged=no; 6.84 |
| p02 | B | 11 s | 2 | 11,838 (+3,331 new) | 876 | $0.05 | converged=no; 6.837916 |

All four answers are right, and every bundle copy was unchanged. In condition A the agent worked
the grid study out by hand from the raw files: on p01 it reached foam-verify's numbers, and on
p02 it found that refining moves the walls through the wall-function switch. It also quoted a
published value "from memory", a known confound (As built, below). In condition B it called
`verification_report` once. Condition B took about a tenth of the time and the usage; at these
rates the 72 scored runs would take about an hour and about $20 at API prices, more if the
evaluation bundles need more reading.

## Building and checking

```console
$ python3 eval/generate.py setup
$ podman run --rm -v "$PWD":/work:z -w /work --entrypoint /bin/bash $IMG eval/run.sh
$ python3 eval/generate.py collect
```

`$IMG` is the pinned image in `studies/README.md`. The new runs take about 7.5 minutes on 24
cores. `eval/build/`, the full cases, is not committed.

[`tests/test_run_agents.py`](../tests/test_run_agents.py) checks the harness without running an
agent: the question, the command, the sandbox's contents, and when a batch stops.

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
