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
value. With twelve bundles every rate is given with its counts. The results, 72 scored runs on
each of two models, are under [The scored runs](#the-scored-runs).

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

A local model runs through the same harness, behind llama.cpp's `llama-server`, which answers
Anthropic's Messages API:

```console
$ uv run --extra mcp python eval/run_agents.py --server http://127.0.0.1:8094 \
      --model qwen3.8-27b-ud-q6k --runs 1
```

Claude Code is the same binary with the same command line, and sends the local model what it
sends Claude: the same system prompt, tools and question, with adaptive thinking at high effort.
Only the environment differs. The server's URL and a placeholder key stand in for the login,
so the sandbox holds no login file. Any background request names the same model. The server's
context window is given in `CLAUDE_CODE_MAX_CONTEXT_TOKENS`: Claude Code does not know a local
model's window, and keeps a session within the one it is given, compacting it if need be. The
request timeout is 30 minutes, the run's own limit, since a long prompt can take a local model
minutes. And `CLAUDE_CODE_MODEL_CAPABILITIES` tells Claude Code that the model takes no system
message after the first. Claude Code sends Claude its environment notes (working folder,
platform, date) as a system message after the question; Qwen's chat template refuses that
message, so Claude Code puts the same notes at the head of the question, as system reminders.

Every run on a local model records the server: as it reports itself, the llama.cpp build, the
model file and its sha256, the context window, the slots and the sampling defaults; and the
command line and `GGML_`/`LLAMA_` environment of the process that listens on its port, which say
what `/props` does not (the cache types or chat template arguments, say), with the home folder
written as `~`. A batch stops before a run if the server does not answer or has changed. With
`--keep-going`, a batch goes on past a run that times out, which counts as always; a run set
aside still stops it.

From the local model's runs on, a transcript is Claude Code's stream-json output as it ran
with two changes, and the run's line in `runs.jsonl` counts each. Its `thinking_tokens`
events are dropped: each holds only a running count of thinking tokens, and `llama-server`
streams thinking a token at a time, so Claude Code writes one per token, megabytes per run;
the thinking itself is in the assistant messages, and the totals in the result. And the home
folder is written as `/home/user`, as in the Opus 5.5 runs: it appears where Claude Code saved
a tool output too long to show, in the sandbox's own home, whose path is the user's.

Every run appends a line to `runs.jsonl` beside the transcripts: the bundle, condition, model and
foam-verify commit, the time taken, the turns, the token usage and its cost at API prices, whether
the bundle copy was unchanged, and the answer's FINAL line. The script never reads the labels. A
run that fails, times out or hits the usage limit stops the batch, and so does a login token close
to expiry, so that no token is refreshed inside a sandbox. A run that did not finish for a reason
outside the agent's answer is set aside (see Scoring); started again, a batch runs the slots set
aside and skips every other run it has. Scored runs only start from committed code, so the commit
each one records is the code it ran; the pilot ran from the working tree, which its index marks
`-dirty`.

**The isolation probe** (2 Nov 2026, Claude Code 2.1.312, Opus 5.5) gave condition B's sandbox a
list of ways out and planted a canary file beside the login file. Reading the labels' path, the
canary or `/proc/1/environ`, and grepping the home folder, were refused. A grep for the canary's
text from `/` and a glob for its name from `/` found nothing, `/tmp` was empty, and foam-verify's
server refused a study outside `/study`. The agent had no instructions from any `CLAUDE.md`,
`AGENTS.md` or memory file. An earlier probe without the sandbox found that Claude Code's
permission rules alone leave `/tmp` readable, where test runs leave copies of the committed
studies with their reports; hence the sandbox. The probe's transcripts name paths in the home
folder and are not committed.

## Scoring

[`score.py`](score.py) scores the runs (`python3 eval/score.py`, or `--pilot` for the pilot) and
writes `scores.jsonl`, one line per run, and `scores.md`, the tables, beside `runs.jsonl`. Its
rules were committed before any scored run, as the labels were, and are the same for every model
and condition:

- **Labels.** `labels.toml` as committed at `90d5c4f`: the scorer checks its sha256 and refuses
  any other file.
- **Which runs count.** A run counts when Claude Code finished it, or when it reached the
  30-minute limit, which counts as an answer without a verdict. A run that did not finish for a
  reason outside the agent's answer is set aside: one that did not start, hit the usage limit or
  another error, or ended without a result, and in condition B one whose foam-verify server was
  not connected at the start. The harness keeps its transcript under a new name
  (`b01-r1.failed-1.jsonl`), marks its line in `runs.jsonl`, and runs the slot again when the
  batch is started again; `scores.md` lists every run set aside. A run that counts is never run
  again or left out.
- **The protocol.** The scorer refuses to score at all if a run that counts broke the protocol:
  a working folder other than `/study`, another model, tools or servers other than the
  condition's (Read, Glob and Grep; in B also foam-verify's tools, with its server connected), a
  bundle copy that changed, uncommitted code, a second run for the same slot, a line of
  `runs.jsonl` that disagrees with its transcript, or a run of a model on a server other than
  the one its first run recorded.
- **The verdict** is read from the answer's FINAL line alone: the last line that starts with
  `FINAL:` (after any Markdown marks, in any case) and names `converged`. The rest of the answer
  is not read, so an answer whose text and FINAL line disagree is scored by its line.
  `converged=yes` is the verdict trustworthy and `converged=no` not trustworthy, in any case and
  whatever follows the word. No FINAL line, or anything else after `converged=` (`maybe`,
  `yes/no`, the question's own `<yes|no>`), is no verdict.
- **Right, false trust, rejected.** A verdict is right when it is the label's. False trust is the
  verdict trustworthy on a bundle labelled not trustworthy; a sound bundle rejected is the
  verdict not trustworthy on one labelled trustworthy. No verdict is never right, and is counted
  on its own, as neither false trust nor a rejection.
- **Value and uncertainty** are the first number after `value=` and `uncertainty=` (`:` also
  does), or none: `none`, `n/a`, a dash, or text that is not a number, which gets a note in
  `scores.jsonl`. A number may start with ±, `+/-`, `~` or ≈, and use a Unicode minus and
  an exponent (`e-4`, `x10^-4`, `×10⁻⁴`). A `%` straight after the uncertainty makes it a
  percentage of the value, and its sign is dropped.
- **Bands.** When both are numbers, the answer's band is value ± uncertainty. On the duct
  bundles (b02, b03, b06, b11) the scorer records whether the band holds the exact f Re
  (`abs(value - exact) <= uncertainty`), whatever the verdict. On the four sound bundles it
  records whether the value lies in the label's band (foam-verify's value and U on the committed
  study), and the ratio of the uncertainty to the label's.
- **Reasons are not scored by the script.** Whether an answer names a label's reason takes
  reading, because answers also name the checks that pass: a word search cannot tell "the value
  is still drifting" from "it isn't caused by unconverged iterations". The transcripts are
  committed for that reading.
- **Rates come with their counts**, per model and condition. Three runs of one bundle are not
  independent, so the table by bundle shows every verdict.
- **Cost** is Claude Code's own count at API prices, for Claude. A local model has none, and
  its runs show `-`.

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

The pilot also tries the scorer, against [`pilot/labels.toml`](pilot/labels.toml): labels for
p01 and p02 in the same form, taken from the committed studies' reports and, unlike the
evaluation's, written after the pilot ran. All four verdicts are right, and on p01 both values lie
in the label's band ([`pilot/runs/scores.md`](pilot/runs/scores.md)).

### The local model

On 3 Nov 2026 p01 also ran on Qwen3.8 27B (`qwen3.8-27b-ud-q6k`: Unsloth's UD-Q6_K GGUF,
sha256 `c9c206812fbe4ac7b76a729e25928b63f2ae89d37f69da7a71c20aec763cd436`), served by
llama.cpp b11678 (Vulkan) on an RTX 5090 Laptop GPU (24 GB):

```console
$ GGML_VK_DISABLE_COOPMAT2=1 llama-server -m Qwen3.8-27B-UD-Q6_K.gguf --alias qwen3.8-27b-ud-q6k \
    --device Vulkan1 -ngl 99 -fit off -c 118784 -ctk q8_0 -ctv q4_0 -fa on -b 2048 -ub 512 \
    -np 1 -t 8 --jinja --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0 --host 127.0.0.1 --port 8094
```

The cache types are what fits a 118,784-token window beside the weights, and the coopmat2 path is
off because with it this file's prompt processing collapses past about 12,000 tokens. The server
ignores Claude Code's `thinking` and `effort` fields, so the model thinks as its chat template
does by default, at effort `xhigh`; the template also maps the `high` that Claude Code asks for to
`xhigh`.

- **The first run was set aside.** Qwen's chat template refused Claude Code's request (a system
  message after the question), and the server answered every try with an error. With
  `CLAUDE_CODE_MODEL_CAPABILITIES` (Running the agents, above) the runs went through.
- **Condition B was right**, in 44 s and 3 turns, with foam-verify's value and U
  (−0.21376 ± 0.000366), as Opus 5.5 gave.
- **Condition A gave no answer in 30 minutes**, which counts as no verdict; Opus 5.5 took 102 s.
  The agent read the raw probe files a few lines at a time (25 tool calls), thought for about
  12,000 tokens at about 21 tokens a second, filled the window, and Claude Code was compacting
  the session when the time ran out.
- **Thinking off does not change that.** A trial with thinking off at the server
  (`--chat-template-kwargs '{"enable_thinking":false}'`), outside the record, had made 38 tool
  calls and been compacted once after 12 minutes on p01 in condition A, with no answer yet. The
  scored runs keep the thinking that Claude Code asks for, as Opus 5.5 had.

These runs predate three changes to the harness. Their `thinking_tokens` events were dropped, and
the home folder written as `/home/user`, afterwards with the harness's own functions
(`drop_progress`, `rename_home`), and their index lines count both; and their server record
lacks the command line and environment that it now holds.

## The scored runs

Each model ran 72 scored runs, three of each bundle in each condition, in three batches of 24,
each batch one run of every bundle in both conditions. Transcripts, index and scores are in
[`runs/`](runs/), and [`runs/scores.md`](runs/scores.md) lists every verdict and stated value.

### Claude Opus 5.5

Claude Opus 5.5's runs (`claude-opus-5-5`) ran on 2 Nov 2026, all from foam-verify at `5239b11`
on Claude Code 2.1.312, and all 72 count: none was set aside, timed out or hit the usage limit,
no tool call was refused, and every bundle copy was unchanged. Together they took 40 minutes and
$14.90 at API prices:

| Condition | Verdict right | False trust | Sound bundles rejected | Bands holding the exact value | Median time | Median turns | Cost at API prices |
|---|---|---|---|---|---|---|---|
| A, the files only | 29 of 36 (81%) | 7 of 24 (29%) | 0 of 12 | 12 of 12 | 46 s | 16.5 | $12.65 |
| B, with foam-verify | 36 of 36 (100%) | 0 of 24 (0%) | 0 of 12 | 7 of 7 | 17 s | 3 | $2.24 |

Condition A trusted b02 (two grids) and b03 (refinement ratios of about 1.10) in all three runs,
and b05 (the 80x80 grid on another convection scheme) in its second run only: it is the one
bundle on which a condition changed its verdict between runs. Condition B gave the same verdict
in all three runs of every bundle.

Eight paths in seven of condition A's transcripts point under the home folder, where Claude Code
saved a tool output too long to show in full; the folder exists only inside that run's sandbox.
The user name in those paths is replaced with `user`; nothing else in any transcript differs from
the recording.

### Qwen3.8 27B, the local model

Qwen3.8 27B's runs (`qwen3.8-27b-ud-q6k`) ran on 3 and 4 Nov 2026, all from foam-verify at
`43dbc32` on Claude Code 2.1.312 and one server, started with the command under
[The local model](#the-local-model); its record is the same in every run. The first batch ran
its twelve runs in condition B before its twelve in A. All 72 count, and one more run was set
aside: in b07's second run in condition A, Claude Code's compaction of the session failed, the
model's summary coming back empty ("summarization produced empty response"), and Claude Code
ended the run with an error. The slot ran again, and that run counts. No tool call was refused
and every bundle copy was unchanged. Together they took 19.7 hours:

| Condition | Verdict right | False trust | Sound bundles rejected | No verdict | Bands holding the exact value | Median time |
|---|---|---|---|---|---|---|
| A, the files only | 4 of 36 (11%) | 0 of 24 (0%) | 0 of 12 | 32 | 2 of 2 | 30 min, the limit |
| B, with foam-verify | 35 of 36 (97%) | 0 of 24 (0%) | 0 of 12 | 1 | 9 of 9 | 72 s |

Every verdict the model gave was right, 39 of 39; each run without one reached the 30-minute
limit. In condition A it answered four times in 36 runs, after 23 to 27 minutes: b03 and b11 in
the first run, b04 in the second and b06 in the third, no bundle twice. Its false trust of none
in A therefore rests on two verdicts on the 24 runs of broken bundles. Most of what it wrote was
thinking, 93% of the characters in condition A and 87% in B, at about 23 tokens a second, and
Claude Code compacted seven of its runs in A and one in B, once each. In condition B it gave
the same verdict in all three runs of eleven bundles. On b10 it asked foam-verify for the report
and then read the raw probe histories in every run: the first run reached the limit, and the
other two said no after 15 and 13 minutes.

The index and scores already held the earlier runs' lines, not yet committed, and the harness
counts any change to a tracked file as uncommitted code. So at each start after the first, those
three files were kept out of that check (moved aside, or marked unchanged for git); the code was
`43dbc32`'s throughout. The harness wrote the home folder as `/home/user` in nine places in five
transcripts, counted by `home_paths_renamed` in the index.

## Building and checking

```console
$ python3 eval/generate.py setup
$ podman run --rm -v "$PWD":/work:z -w /work --entrypoint /bin/bash $IMG eval/run.sh
$ python3 eval/generate.py collect
```

`$IMG` is the pinned image in `studies/README.md`. The new runs take about 7.5 minutes on 24
cores. `eval/build/`, the full cases, is not committed.

[`tests/test_run_agents.py`](../tests/test_run_agents.py) checks the harness without running an
agent: the question, the command, the sandbox's contents, when a batch stops and which runs it
sets aside.

[`tests/test_score.py`](../tests/test_score.py) holds the scorer to its rules on hand-written
answer lines and made-up transcripts, one for each way a run can be set aside or refused, and
checks that the pilot's committed scores are what it writes.

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
