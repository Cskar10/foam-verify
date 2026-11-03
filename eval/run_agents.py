"""Run AI agents on the evaluation bundles: Claude Code headless, with or without foam-verify.

    uv run --extra mcp python eval/run_agents.py --pilot                   # p01, p02, A and B, once
    uv run --extra mcp python eval/run_agents.py --bundles b01 b02 --runs 3
    uv run --extra mcp python eval/run_agents.py --probe                   # check the isolation
    uv run --extra mcp python eval/run_agents.py --server http://127.0.0.1:8094 \
        --model qwen3.8-27b-ud-q6k --runs 1                                # a local model

Every run gets one bundle and one question (PROMPT), in one of two conditions:

- A: the agent may read the bundle's files with Claude Code's Read, Glob and Grep, and nothing
  else;
- B: the same, plus foam-verify's MCP server with the bundle as its only root.

Each run works on a fresh copy of the bundle, inside a bubblewrap sandbox (Linux namespaces) that
holds only the system's /usr and /etc, an empty /tmp, its own /proc, the bundle copy read-only at
/study (the working directory), and in /home only what the run needs: the Claude Code binary, the
login file read-only, and for condition B foam-verify's code and Python. The repository's
labels, the committed studies and everything else on the machine are simply not there. The agent's
tools are also refused any read under /home or /proc, which keeps it away from the login file.
Nothing of the user's own Claude Code setup is loaded: no user settings (hooks, plugins,
permissions), no CLAUDE.md or auto-memory, no skills or slash commands, and no MCP server but
foam-verify's in condition B. The environment is rebuilt from scratch.

The transcript of every run (Claude Code's stream-json output, less its thinking_tokens progress
events, and with the home folder written as /home/user) is saved, and each run appends a line to
runs.jsonl beside the transcripts: the settings, the time taken, the usage and the answer's FINAL
line. This script never reads the labels; scoring is separate (score.py). A run that fails, times
out or hits the subscription's usage limit stops the batch, and so does a login token close to
expiry, so that no token is ever refreshed inside the sandbox, where the login file is read-only. A
run that did not finish for a reason outside the agent's answer (set_aside_reason) is set aside: its
transcript is kept under a new name and its record marked, so that the batch runs that slot again
when it is started again. Every other run is skipped when a batch is started again, a timed-out one
included. Scored runs only start from committed code; the pilot may run from a working tree.

A local model runs the same way, behind a server that answers Anthropic's Messages API (llama.cpp's
llama-server): Claude Code sends it the requests it sends Claude, through the same sandbox, which
then holds no login file. Each run records the server as it reports itself (llama.cpp build,
model file and its sha256, context window, sampling defaults), and a batch stops before a run if
the server is gone or has changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUNDLES = HERE / "bundles"
PILOT_BUNDLES = HERE / "pilot" / "bundles"
DEFAULT_MODEL = "claude-opus-5-5"
CONDITIONS = ("A", "B")
TIMEOUT_S = 30 * 60
STUDY = "/study"  # the bundle copy, inside the sandbox

PROMPT = """\
The current folder holds a CFD grid study: study.toml describes it, and each grid level's \
OpenFOAM case is in its own subfolder.

Is the reported value of {qoi} converged and mesh-independent? Give the value with its \
uncertainty, or say why you can't.

End your answer with this line, filled in:
FINAL: converged=<yes|no>; value=<number|none>; uncertainty=<number|none>
value is the reported value of {qoi}; uncertainty is its 95% uncertainty U, such that the \
mesh-independent value lies within value +/- U. converged=yes means that the value is converged \
and mesh-independent."""

TOOLS = "Read,Glob,Grep"
# Refused to the agent's tools even inside the sandbox: the login file lives under /home, and
# /proc holds the processes' environments.
DENY = ("Read(//home/**)", "Read(//proc/**)")
SERVER = "foam-verify"
# The switches that keep the user's own Claude Code setup out of a run.
SWITCHES = {
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}
CREDENTIALS = Path.home() / ".claude" / ".credentials.json"
# llama-server needs no key, but Claude Code will not start without one.
LOCAL_TOKEN = "local"
# A run never starts with less login time left than its timeout and this margin.
TOKEN_MARGIN_S = 15 * 60
# A FINAL line, after any Markdown marks: quote, list, heading, emphasis or code.
_FINAL = re.compile(r"^[ \t>*_`#-]*FINAL\s*:.*$", re.MULTILINE | re.IGNORECASE)


def prompt(qoi: str) -> str:
    return PROMPT.format(qoi=qoi)


def bundle_qoi(bundle: Path) -> str:
    """The one QoI a bundle asks about, from its study.toml."""
    qois = tomllib.loads((bundle / "study.toml").read_text(encoding="utf-8")).get("qoi", [])
    if len(qois) != 1:
        raise SystemExit(f"{bundle}: a bundle asks about exactly one qoi, found {len(qois)}")
    return str(qois[0]["name"])


def claude_binary() -> Path:
    found = shutil.which("claude")
    if found is None:
        raise SystemExit("claude not found on PATH")
    return Path(found).resolve()


def server_script() -> Path:
    """foam-verify's console script in this environment (uv run --extra mcp)."""
    script = Path(sys.executable).parent / "foam-verify"
    if not script.is_file():
        raise SystemExit(f"{script} not found: run this with uv run --extra mcp python ...")
    return script


def mcp_config(condition: str) -> dict[str, Any]:
    """Condition A: no MCP server. B: foam-verify's, with the study copy as its only root."""
    if condition == "A":
        return {"mcpServers": {}}
    if condition == "B":
        return {
            "mcpServers": {
                SERVER: {"command": str(server_script()), "args": ["mcp", "--root", STUDY]}
            }
        }
    raise ValueError(f"unknown condition {condition!r}")


def command(condition: str, model: str, text: str, claude: Path) -> list[str]:
    """Claude Code's command line, as it runs inside the sandbox."""
    allowed = TOOLS + (f",mcp__{SERVER}" if condition == "B" else "")
    return [
        str(claude),
        "-p",
        text,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--tools",
        TOOLS,
        "--allowedTools",
        allowed,
        "--disallowedTools",
        *DENY,
        "--permission-mode",
        "dontAsk",
        "--setting-sources",
        "project",
        "--strict-mcp-config",
        "--mcp-config",
        json.dumps(mcp_config(condition)),
        "--disable-slash-commands",
        "--no-session-persistence",
    ]


@dataclass(frozen=True)
class Server:
    """A local model's server: its URL, and what each run records of it."""

    url: str
    record: dict[str, Any]


def server_props(url: str) -> dict[str, Any]:
    """llama-server's own account of itself (GET /props)."""
    with urllib.request.urlopen(f"{url}/props", timeout=30) as response:
        props: dict[str, Any] = json.loads(response.read())
    return props


def describe(props: dict[str, Any]) -> dict[str, Any]:
    """What a run records of its server, from /props: the llama.cpp build, the model file's name
    (not its path, which names the user) and alias, the context window, the slots and the
    sampling defaults."""
    settings = props["default_generation_settings"]
    params = settings["params"]
    return {
        "build": props["build_info"],
        "model_file": Path(props["model_path"]).name,
        "model_alias": props["model_alias"],
        "n_ctx": int(settings["n_ctx"]),
        "slots": int(props["total_slots"]),
        "sampling": {
            "temperature": round(float(params["temperature"]), 6),
            "top_k": int(params["top_k"]),
            "top_p": round(float(params["top_p"]), 6),
            "min_p": round(float(params["min_p"]), 6),
        },
    }


def server_process(url: str) -> dict[str, list[str]]:
    """How the server was started, which /props does not say (its KV cache types or chat template
    arguments, say): the command line of the process that listens on its port on this machine,
    and its GGML_ and LLAMA_ environment settings, with the home folder written as ~."""
    port = urllib.parse.urlsplit(url).port
    listening = subprocess.run(
        ["ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True, check=True
    ).stdout
    pids = set(re.findall(r"pid=(\d+)", listening))
    if len(pids) != 1:
        raise SystemExit(f"no single local process listens on port {port}: {listening!r}")
    proc = Path("/proc") / pids.pop()
    home = str(Path.home())

    def strings(name: str) -> list[str]:
        raw = (proc / name).read_bytes().decode("utf-8", errors="replace")
        return [s.replace(home, "~") for s in raw.split("\0") if s]

    settings = sorted(s for s in strings("environ") if s.startswith(("GGML_", "LLAMA_")))
    return {"command": strings("cmdline"), "env": settings}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 24):
            digest.update(chunk)
    return digest.hexdigest()


def local_server(url: str, model: str) -> Server:
    """The server at url, which must serve model; its model file is hashed once, here."""
    url = url.rstrip("/")
    props = server_props(url)
    record = describe(props) | server_process(url)
    if record["model_alias"] != model:
        raise SystemExit(f"{url} serves {record['model_alias']!r}, not {model!r}")
    record["model_sha256"] = file_sha256(Path(props["model_path"]))
    return Server(url, record)


def server_problem(server: Server) -> str | None:
    """Why the server cannot take the next run: gone, or not as it was when the batch started."""
    try:
        now = describe(server_props(server.url)) | server_process(server.url)
    except (OSError, ValueError, KeyError, SystemExit, subprocess.CalledProcessError) as error:
        return f"the server at {server.url} does not answer as llama-server: {error}"
    started = {k: v for k, v in server.record.items() if k != "model_sha256"}
    if now != started:
        return f"the server at {server.url} has changed: {now}, not {started}"
    return None


def environment(server: Server | None = None) -> dict[str, str]:
    """The sandbox's whole environment: who and where the user is, and the switches. For a local
    model, also its server's URL, a placeholder key, the same model for any background request,
    the server's context window (Claude Code does not know this model's, and keeps a session
    within the one it is given), a request timeout as long as a run's limit (a long prompt can
    take a local model minutes), and Claude Code's own switch for a model that takes no system
    message after the first: Claude Code then sends its environment notes at the head of the
    question, as a system reminder, where for Claude it sends them as a system message after it
    (Qwen's chat template refuses that message)."""
    home = Path.home()
    env = {
        "HOME": str(home),
        "USER": os.environ.get("USER", home.name),
        "LOGNAME": os.environ.get("LOGNAME", home.name),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        **SWITCHES,
    }
    if server is not None:
        model = str(server.record["model_alias"])
        env |= {
            "ANTHROPIC_BASE_URL": server.url,
            "ANTHROPIC_AUTH_TOKEN": LOCAL_TOKEN,
            "ANTHROPIC_SMALL_FAST_MODEL": model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(server.record["n_ctx"]),
            "API_TIMEOUT_MS": str(TIMEOUT_S * 1000),
            "CLAUDE_CODE_MODEL_CAPABILITIES": f"{model}=-mid_conv_system",
        }
    return env


def sandbox(
    inner: Sequence[str],
    study: Path,
    claude: Path,
    *,
    server: bool,
    extra: Sequence[tuple[Path, str]] = (),
    local: Server | None = None,
) -> list[str]:
    """bwrap around inner: the system, the study read-only at STUDY, and in /home only the
    Claude Code binary, the login file (read-only; none for a local model) and, with server,
    foam-verify and Python."""
    home = Path.home()
    argv = [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--clearenv",
    ]
    for key, value in environment(local).items():
        argv += ["--setenv", key, value]
    argv += ["--ro-bind", "/usr", "/usr"]
    for link in ("bin", "sbin", "lib", "lib64"):
        argv += ["--symlink", f"usr/{link}", f"/{link}"]
    argv += ["--ro-bind", "/etc", "/etc", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    argv += ["--tmpfs", "/home", "--dir", str(home)]
    argv += ["--ro-bind", str(claude), str(claude)]
    argv += ["--tmpfs", str(home / ".claude")]
    if local is None:
        argv += ["--ro-bind", str(CREDENTIALS), str(CREDENTIALS)]
    if server:
        python = Path(sys.base_prefix).resolve().parent  # every Python uv manages, aliases too
        for path in (ROOT / ".venv", ROOT / "src", python):
            argv += ["--ro-bind", str(path), str(path)]
    for source, target in extra:
        argv += ["--ro-bind", str(source), target]
    argv += ["--ro-bind", str(study), STUDY, "--chdir", STUDY]
    return [*argv, *inner]


def token_seconds_left() -> float:
    """Seconds until the Claude login's access token expires; only expiresAt is read."""
    data = json.loads(CREDENTIALS.read_text(encoding="utf-8"))
    return float(data["claudeAiOauth"]["expiresAt"]) / 1000 - time.time()


def tree_hash(folder: Path) -> dict[str, str]:
    """Every file under folder by its relative path, with its sha256."""
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def final_line(text: str) -> str | None:
    """The answer line: the last line that starts with FINAL: (after any Markdown marks) and names
    converged, as written."""
    lines = [line for line in _FINAL.findall(text) if "converged" in line.lower()]
    return lines[-1].strip() if lines else None


def set_aside_reason(record: dict[str, Any]) -> str | None:
    """Why a run did not finish for a reason outside the agent's answer, so that it is set aside
    and run again; None for a run that counts. A run counts when Claude Code finished it, or when
    it reached the time limit (an answer without a verdict). In condition B, a foam-verify server
    that was not connected at the start makes the run not a condition-B run."""
    if record["cwd"] is None:
        return "did not start"
    if record["condition"] == "B":
        servers: list[dict[str, Any]] = record["mcp_servers"] or []
        if [(s.get("name"), s.get("status")) for s in servers] != [(SERVER, "connected")]:
            return "foam-verify not connected"
    if record["timed_out"]:
        return None
    if record["hit_limit"]:
        return "usage limit"
    if record["is_error"] is None:
        return "no result"
    if record["is_error"]:
        return "error"
    if record["exit_code"] != 0:
        return f"exit code {record['exit_code']}"
    return None


def set_aside(transcript: Path) -> Path:
    """Move a run's transcript (and its stderr) out of its slot, keeping both, so that the slot
    runs again: b01-r1.jsonl becomes b01-r1.failed-1.jsonl, then -2 and so on."""
    n = 1
    while (moved := transcript.with_name(f"{transcript.stem}.failed-{n}.jsonl")).exists():
        n += 1
    transcript.rename(moved)
    errors = transcript.with_suffix(".stderr")
    if errors.exists():
        errors.rename(moved.with_suffix(".stderr"))
    return moved


@dataclass(frozen=True)
class Summary:
    """What a transcript says about its run."""

    init: dict[str, Any] | None
    result: dict[str, Any] | None
    compactions: int = 0

    @property
    def answer(self) -> str:
        return str((self.result or {}).get("result") or "")

    @property
    def hit_limit(self) -> bool:
        result = self.result or {}
        return bool(result.get("is_error")) and "limit" in self.answer.lower()


def _is_progress(line: str) -> bool:
    if not line.lstrip().startswith("{"):
        return False
    try:
        event: Any = json.loads(line)  # an object, since the line starts with {
    except json.JSONDecodeError:
        return False
    return event.get("type") == "system" and event.get("subtype") == "thinking_tokens"


def drop_progress(transcript: Path) -> int:
    """Drop Claude Code's thinking_tokens events from a transcript and return how many there were.
    They hold only a running count of thinking tokens; a local model's server streams its thinking
    a token at a time, and Claude Code writes one for each, megabytes per run. The thinking itself
    is in the assistant messages, and the totals in the result; nothing else is touched."""
    lines = transcript.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in lines if not _is_progress(line)]
    if len(kept) != len(lines):
        transcript.write_text("".join(kept), encoding="utf-8")
    return len(lines) - len(kept)


def rename_home(transcript: Path) -> int:
    """Write the home folder as /home/user in a transcript, and return how many times it was
    there. It appears where Claude Code saved a tool output too long to show, in the sandbox's
    own (empty) home, whose path is the user's."""
    home = f"{Path.home()}/"
    text = transcript.read_text(encoding="utf-8")
    found = text.count(home)
    if found:
        transcript.write_text(text.replace(home, "/home/user/"), encoding="utf-8")
    return found


def summarise(transcript: Path) -> Summary:
    init = result = None
    compactions = 0
    for line in transcript.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            init = event
        elif event.get("type") == "system" and event.get("subtype") == "compact_boundary":
            compactions += 1
        elif event.get("type") == "result":
            result = event
    return Summary(init, result, compactions)


def git_head() -> str:
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return head + ("-dirty" if dirty else "")


def run_one(
    bundle: Path,
    condition: str,
    model: str,
    transcript: Path,
    *,
    text: str | None = None,
    extra: Sequence[tuple[Path, str]] = (),
    timeout: float = TIMEOUT_S,
    server: Server | None = None,
) -> dict[str, Any]:
    """One agent run on a fresh copy of bundle, on server's model if given; the transcript goes
    to transcript."""
    claude = claude_binary()
    before = tree_hash(bundle)
    with tempfile.TemporaryDirectory(prefix="study-") as work:
        study = Path(work)
        shutil.copytree(bundle, study, dirs_exist_ok=True)
        inner = command(condition, model, text or prompt(bundle_qoi(bundle)), claude)
        argv = sandbox(inner, study, claude, server=condition == "B", extra=extra, local=server)
        transcript.parent.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        started = datetime.now(UTC).isoformat(timespec="seconds")
        timed_out = False
        errors = transcript.with_suffix(".stderr")
        with transcript.open("w") as out, errors.open("w") as err:
            proc = subprocess.Popen(
                argv,
                cwd=study,
                env={"PATH": "/usr/bin:/bin"},
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                code = proc.wait()
                timed_out = True
        duration = time.monotonic() - start
        unchanged = tree_hash(study) == before
    if errors.stat().st_size == 0:
        errors.unlink()
    dropped = drop_progress(transcript)
    renamed = rename_home(transcript)
    summary = summarise(transcript)
    result = summary.result or {}
    init = summary.init or {}
    return {
        "bundle": bundle.name,
        "condition": condition,
        "model": model,
        "started": started,
        "duration_s": round(duration, 1),
        "exit_code": code,
        "timed_out": timed_out,
        "unchanged": unchanged,
        "claude_code_version": init.get("claude_code_version"),
        "cwd": init.get("cwd"),
        "tools": init.get("tools"),
        "mcp_servers": init.get("mcp_servers"),
        "is_error": result.get("is_error"),
        "num_turns": result.get("num_turns"),
        "total_cost_usd": result.get("total_cost_usd"),
        "usage": result.get("usage"),
        "permission_denials": len(result.get("permission_denials") or []),
        "final": final_line(summary.answer),
        "hit_limit": summary.hit_limit,
        "compactions": summary.compactions,
        "progress_events_dropped": dropped,
        "home_paths_renamed": renamed,
        **({} if server is None else {"server": server.record}),
    }


def run_batch(
    bundles: Sequence[Path],
    conditions: Sequence[str],
    runs: int,
    model: str,
    out: Path,
    server: Server | None = None,
    *,
    keep_going: bool = False,
) -> int:
    """Run every slot not yet done. A run set aside, or one that hit the usage limit, stops the
    batch; so does a timed-out run, unless keep_going (it counts all the same)."""
    head = git_head()
    index = out / "runs.jsonl"
    done = 0
    for k in range(1, runs + 1):
        for bundle in bundles:
            for condition in conditions:
                transcript = out / model / condition / f"{bundle.name}-r{k}.jsonl"
                if transcript.exists():
                    print(f"{transcript.relative_to(out)}: exists, skipped")
                    continue
                if server is not None:
                    problem = server_problem(server)
                    if problem is not None:
                        print(f"{problem}: stopping before the next run")
                        return done
                else:
                    left = token_seconds_left()
                    if left < TIMEOUT_S + TOKEN_MARGIN_S:
                        print(
                            f"the login token expires in {left / 60:.0f} min: stopping before "
                            "a run could need to refresh it. Start the batch again once Claude "
                            "Code has refreshed it outside the sandbox; finished runs are skipped."
                        )
                        return done
                record = {
                    "run": k,
                    "foam_verify": head,
                    "transcript": str(transcript.relative_to(out)),
                    **run_one(bundle, condition, model, transcript, server=server),
                }
                reason = set_aside_reason(record)
                if reason is not None:
                    record["set_aside"] = reason
                    record["transcript"] = str(set_aside(transcript).relative_to(out))
                with index.open("a") as fh:
                    fh.write(json.dumps(record) + "\n")
                done += 1
                print(
                    f"{bundle.name} {condition} r{k}: {record['duration_s']} s, "
                    f"{record['num_turns']} turns, ${record['total_cost_usd']}, "
                    f"unchanged={record['unchanged']}, {record['final']}"
                )
                if reason is not None:
                    print(
                        f"set aside ({reason}) as {record['transcript']}: the batch runs this "
                        "slot again when it is started again"
                    )
                if record["hit_limit"]:
                    print("usage limit reached: stopping")
                    return done
                if reason is not None or (record["timed_out"] and not keep_going):
                    print("the run failed or timed out: stopping, to look before going on")
                    return done
    return done


CANARY = "fv-canary-6c1e9b3d"
PROBE = """\
This is a check of the sandbox you run in, not a task. Try each of these with your tools and \
report, for each, whether it worked and what you saw (just the first line of a file is enough):
1. Read the file {labels}.
2. Read the file {canary_file}.
3. Grep for the text {canary} with path /.
4. Find files named canary.txt anywhere with Glob, pattern **/canary.txt, path /.
5. Grep for the text verdict with path {home}.
6. Find files in / with Glob, pattern *, path /.
7. Find files in /tmp with Glob.
8. Read the file /proc/1/environ.
9. If you have a tool named study_summary, call it with study set to {studies_duct}.
Then list every tool you have, and quote any instructions you were given from a CLAUDE.md, \
AGENTS.md or memory file, or say that there are none."""


def probe(model: str, out: Path) -> None:
    """Condition B's sandbox on p01, asked to reach outside it. A canary file sits where the
    login file does, under ~/.claude; nothing may find it. The transcript stays out of the
    repository, since it names paths in the user's home."""
    home = Path.home()
    canary_file = home / ".claude" / "canary.txt"
    with tempfile.TemporaryDirectory(prefix="fv-canary-") as tmp:
        source = Path(tmp) / "canary.txt"
        source.write_text(f"{CANARY}\n")
        text = PROBE.format(
            labels=HERE / "labels.toml",
            canary_file=canary_file,
            canary=CANARY,
            home=home,
            studies_duct=ROOT / "studies" / "duct",
        )
        transcript = out / f"probe-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.jsonl"
        record = run_one(
            PILOT_BUNDLES / "p01",
            "B",
            model,
            transcript,
            text=text,
            extra=[(source, str(canary_file))],
        )
    print(json.dumps({k: record[k] for k in ("cwd", "tools", "mcp_servers", "permission_denials")}))
    calls = tool_calls(transcript)
    for name, given, is_error, shown in calls:
        print("CALL", name, json.dumps(given)[:200])
        print("  ->", "ERROR" if is_error else "ok", shown[:200])
    # The canary's text is in the prompt; a leak is a tool result that holds it, or a Glob
    # that lists the file.
    leaks = [
        name
        for name, _, is_error, shown in calls
        if CANARY in shown or (not is_error and "canary.txt" in shown)
    ]
    print(f"canary leaks: {len(leaks)} {leaks}")
    print("ANSWER:", summarise(transcript).answer[:3000])
    print(f"transcript: {transcript}")


def tool_calls(transcript: Path) -> list[tuple[str, Any, bool, str]]:
    """Each tool call in a transcript: its name, input, whether it failed, and its result."""
    uses: dict[str, tuple[str, Any]] = {}
    calls: list[tuple[str, Any, bool, str]] = []
    for line in transcript.read_text(encoding="utf-8").splitlines():
        event = json.loads(line) if line.strip() else {}
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                uses[str(block.get("id"))] = (str(block.get("name")), block.get("input"))
            elif block.get("type") == "tool_result":
                name, given = uses.get(str(block.get("tool_use_id")), ("?", None))
                result = block.get("content")
                shown = result if isinstance(result, str) else json.dumps(result)
                calls.append((name, given, bool(block.get("is_error")), shown))
    return calls


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--bundles", nargs="+", metavar="ID", help="bundle ids, default all")
    parser.add_argument("--pilot", action="store_true", help="the pilot bundles p01 and p02")
    parser.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=list(CONDITIONS))
    parser.add_argument("--runs", type=int, default=1, help="runs per bundle and condition")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--server",
        metavar="URL",
        help="a local model's llama-server (Anthropic Messages API); --model names its model",
    )
    parser.add_argument("--out", type=Path, help="default eval/runs, or eval/pilot/runs")
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="go on past a run that times out (it counts as always); a failed run still stops",
    )
    parser.add_argument("--probe", action="store_true", help="check the isolation, then stop")
    args = parser.parse_args(argv)
    if shutil.which("bwrap") is None:
        parser.error("bubblewrap (bwrap) is required: every run is sandboxed")
    if args.server is not None and args.model == DEFAULT_MODEL:
        parser.error("--server: name the model it serves with --model")
    if args.probe:
        probe(args.model, Path(tempfile.mkdtemp(prefix="fv-probe-")))
        return 0
    if not args.pilot and git_head().endswith("-dirty"):
        parser.error("commit first: a scored run records the commit it ran from")
    root = PILOT_BUNDLES if args.pilot else BUNDLES
    names = args.bundles or sorted(p.name for p in root.iterdir() if (p / "study.toml").is_file())
    bundles = [root / name for name in names]
    for bundle in bundles:
        if not (bundle / "study.toml").is_file():
            parser.error(f"no bundle {bundle.name} in {root}")
    out = args.out or (HERE / "pilot" / "runs" if args.pilot else HERE / "runs")
    server = None if args.server is None else local_server(args.server, args.model)
    if server is not None:
        print(f"server: {json.dumps(server.record)}")
    done = run_batch(
        bundles, args.conditions, args.runs, args.model, out, server, keep_going=args.keep_going
    )
    print(f"{done} runs; index {out / 'runs.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
