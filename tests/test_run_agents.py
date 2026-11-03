"""The agent harness (eval/run_agents.py) without running an agent: the prompt, the command,
the sandbox it runs in, and how a batch reads transcripts and decides to stop."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import sys
import time
import tomllib
import urllib.error
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_agents", EVAL / "run_agents.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_agents"] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


ra = load()
CLAUDE = Path("/opt/claude/claude")


def option(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def binds(argv: list[str]) -> dict[str, str]:
    """Every --ro-bind target in a bwrap command, with its source."""
    return {argv[i + 2]: argv[i + 1] for i, a in enumerate(argv) if a == "--ro-bind"}


def test_the_prompt_asks_the_plan_s_question_and_fixes_the_last_line() -> None:
    text = ra.prompt("u_min")
    assert "Is the reported value of u_min converged and mesh-independent?" in text
    assert "Give the value with its uncertainty, or say why you can't." in text
    assert "FINAL: converged=<yes|no>; value=<number|none>; uncertainty=<number|none>" in text
    assert "95% uncertainty U" in text
    for word in ("foam-verify", "trust", "label", "GCI", "Richardson"):
        assert word not in text, word


def test_every_bundle_asks_about_its_label_s_qoi() -> None:
    labels = tomllib.loads((EVAL / "labels.toml").read_text(encoding="utf-8"))["bundle"]
    for label in labels:
        assert ra.bundle_qoi(EVAL / "bundles" / label["id"]) == label["qoi"], label["id"]
    assert ra.bundle_qoi(EVAL / "pilot" / "bundles" / "p01") == "u_min"
    assert ra.bundle_qoi(EVAL / "pilot" / "bundles" / "p02") == "xR/H"


@pytest.mark.parametrize("condition", ["A", "B"])
def test_the_command_allows_reading_only(condition: str) -> None:
    argv = ra.command(condition, "claude-opus-5-5", "question", CLAUDE)
    assert argv[:3] == [str(CLAUDE), "-p", "question"]
    assert option(argv, "--model") == "claude-opus-5-5"
    assert option(argv, "--tools") == "Read,Glob,Grep"
    assert option(argv, "--permission-mode") == "dontAsk"
    assert option(argv, "--setting-sources") == "project"
    assert option(argv, "--output-format") == "stream-json"
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in argv
    deny = argv.index("--disallowedTools")
    assert argv[deny + 1 : deny + 3] == ["Read(//home/**)", "Read(//proc/**)"]
    servers = json.loads(option(argv, "--mcp-config"))["mcpServers"]
    allowed = option(argv, "--allowedTools").split(",")
    if condition == "A":
        assert servers == {} and allowed == ["Read", "Glob", "Grep"]
    else:
        assert list(servers) == ["foam-verify"]
        assert servers["foam-verify"]["args"] == ["mcp", "--root", "/study"]
        assert allowed == ["Read", "Glob", "Grep", "mcp__foam-verify"]


def test_an_unknown_condition_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown condition"):
        ra.mcp_config("C")


def test_the_environment_holds_nothing_from_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-for-the-agent")
    monkeypatch.setenv("SOME_MCP_TOKEN", "secret")
    env = ra.environment()
    assert set(env) == {"HOME", "USER", "LOGNAME", "PATH", "LANG", "TERM", *ra.SWITCHES}
    assert env["PATH"] == "/usr/bin:/bin"
    assert all(value == "1" for key, value in env.items() if key in ra.SWITCHES)
    assert "CLAUDE_CODE_DISABLE_CLAUDE_MDS" in ra.SWITCHES


@pytest.mark.parametrize("server", [False, True])
def test_the_sandbox_holds_the_study_read_only_and_little_else(
    server: bool, tmp_path: Path
) -> None:
    inner = ["claude", "-p", "q"]
    argv = ra.sandbox(inner, tmp_path, CLAUDE, server=server)
    assert argv[0] == "bwrap" and argv[-3:] == inner
    for flag in ("--unshare-pid", "--clearenv", "--die-with-parent", "--new-session"):
        assert flag in argv
    home = str(Path.home())
    for a, b in (("--tmpfs", "/tmp"), ("--tmpfs", "/home"), ("--tmpfs", f"{home}/.claude")):
        assert any(argv[i] == a and argv[i + 1] == b for i in range(len(argv) - 1)), b
    bound = binds(argv)
    assert bound["/study"] == str(tmp_path) and option(argv, "--chdir") == "/study"
    assert bound[str(ra.CREDENTIALS)] == str(ra.CREDENTIALS)
    assert bound[str(CLAUDE)] == str(CLAUDE)
    # Nothing of the repository but foam-verify's code and environment, and those only for B.
    assert "--bind" not in argv  # every bind is read-only
    repo = {t for t in bound if t.startswith(str(ROOT))}
    assert repo == ({str(ROOT / ".venv"), str(ROOT / "src")} if server else set())
    for target in bound:
        assert not target.startswith((str(EVAL), str(ROOT / "studies"))), target
        assert target != home and target != str(ROOT), target


def test_extra_binds_go_where_asked(tmp_path: Path) -> None:
    source = tmp_path / "canary.txt"
    argv = ra.sandbox(["x"], tmp_path, CLAUDE, server=False, extra=[(source, "/somewhere")])
    assert binds(argv)["/somewhere"] == str(source)


def test_the_token_time_is_read_from_expires_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    login = tmp_path / ".credentials.json"
    expires = (time.time() + 3600) * 1000
    login.write_text(json.dumps({"claudeAiOauth": {"expiresAt": expires, "accessToken": "x"}}))
    monkeypatch.setattr(ra, "CREDENTIALS", login)
    assert ra.token_seconds_left() == pytest.approx(3600, abs=5)


def test_final_line_is_the_last_one_written() -> None:
    answer = (
        "The study is fine.\n"
        "FINAL: converged=no; value=none; uncertainty=none\n"
        "On reflection:\n"
        "**FINAL: converged=yes; value=-0.2138; uncertainty=0.0004**\n"
    )
    assert ra.final_line(answer) == "**FINAL: converged=yes; value=-0.2138; uncertainty=0.0004**"
    assert ra.final_line("no answer line") is None
    # After Markdown marks, in any case; a FINAL line that does not name converged is not one.
    marked = "> `final: converged=no; value=none; uncertainty=none`\nFinal: done.\n"
    assert ra.final_line(marked) == "> `final: converged=no; value=none; uncertainty=none`"


def write_transcript(path: Path, events: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return path


INIT = {"type": "system", "subtype": "init", "tools": ["Read"], "claude_code_version": "x"}


def result(text: str, *, error: bool = False) -> dict[str, Any]:
    return {"type": "result", "is_error": error, "result": text, "num_turns": 3}


def test_summarise_reads_init_and_result_and_spots_the_usage_limit(tmp_path: Path) -> None:
    good = ra.summarise(write_transcript(tmp_path / "a.jsonl", [INIT, result("OK")]))
    assert good.init == INIT and good.answer == "OK" and not good.hit_limit
    limited = write_transcript(
        tmp_path / "b.jsonl", [INIT, result("You've hit your 5-hour limit", error=True)]
    )
    assert ra.summarise(limited).hit_limit
    broken = tmp_path / "c.jsonl"
    broken.write_text("not json\n" + json.dumps(INIT) + "\n")
    assert ra.summarise(broken).result is None


def test_tool_calls_pair_each_result_with_its_call(tmp_path: Path) -> None:
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "x"}}
                ]
            },
        },
        {"type": "user", "message": "a plain string message"},
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "no"}
                ]
            },
        },
    ]
    calls = ra.tool_calls(write_transcript(tmp_path / "t.jsonl", events))
    assert calls == [("Read", {"file_path": "x"}, True, "no")]


def test_tree_hash_sees_any_change(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f").write_text("1")
    before = ra.tree_hash(tmp_path)
    (tmp_path / "a" / "f").write_text("2")
    assert ra.tree_hash(tmp_path) != before


# --- the batch, with a stand-in for the agent ----------------------------------------------


CONNECTED = [{"name": "foam-verify", "status": "connected"}]


def record(**changes: Any) -> dict[str, Any]:
    base = {
        "condition": "A",
        "cwd": "/study",
        "exit_code": 0,
        "mcp_servers": CONNECTED,
        "duration_s": 1.0,
        "num_turns": 2,
        "total_cost_usd": 0.1,
        "unchanged": True,
        "final": "FINAL: converged=no; value=none; uncertainty=none",
        "hit_limit": False,
        "is_error": False,
        "timed_out": False,
    }
    return {**base, **changes}


def fake_batch(
    monkeypatch: pytest.MonkeyPatch,
    out: Path,
    records: list[dict[str, Any]],
    token_s: float = 10 * 3600,
) -> tuple[int, list[tuple[str, str]]]:
    calls: list[tuple[str, str]] = []

    def run_one(
        bundle: Path, condition: str, model: str, transcript: Path, server: Any = None
    ) -> dict[str, Any]:
        calls.append((bundle.name, condition))
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("{}\n")
        return {**records[len(calls) - 1], "condition": condition}

    monkeypatch.setattr(ra, "run_one", run_one)
    monkeypatch.setattr(ra, "git_head", lambda: "abc123")
    monkeypatch.setattr(ra, "token_seconds_left", lambda: token_s)
    bundles = [EVAL / "pilot" / "bundles" / "p01", EVAL / "pilot" / "bundles" / "p02"]
    done = ra.run_batch(bundles, ["A", "B"], 1, "m", out)
    return done, calls


def test_a_batch_runs_every_bundle_and_condition_and_indexes_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    done, calls = fake_batch(monkeypatch, tmp_path, [record()] * 4)
    assert done == 4 and calls == [("p01", "A"), ("p01", "B"), ("p02", "A"), ("p02", "B")]
    index = [json.loads(line) for line in (tmp_path / "runs.jsonl").read_text().splitlines()]
    assert [r["transcript"] for r in index] == ["m/A/p01-r1.jsonl", "m/B/p01-r1.jsonl"] + [
        "m/A/p02-r1.jsonl",
        "m/B/p02-r1.jsonl",
    ]
    assert {r["foam_verify"] for r in index} == {"abc123"}
    # Started again, the batch skips what is done.
    done, calls = fake_batch(monkeypatch, tmp_path, [])
    assert done == 0 and calls == []


@pytest.mark.parametrize(
    "bad", [{"hit_limit": True, "is_error": True}, {"is_error": True}, {"timed_out": True}]
)
def test_a_batch_stops_at_a_failed_run(
    bad: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    done, calls = fake_batch(monkeypatch, tmp_path, [record(), record(**bad), record(), record()])
    assert done == 2 and len(calls) == 2


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({}, None),
        ({"condition": "B"}, None),
        ({"cwd": None}, "did not start"),
        ({"condition": "B", "mcp_servers": []}, "foam-verify not connected"),
        (
            {"condition": "B", "mcp_servers": [{"name": "foam-verify", "status": "pending"}]},
            "foam-verify not connected",
        ),
        ({"timed_out": True, "is_error": None, "exit_code": -9}, None),
        ({"hit_limit": True, "is_error": True}, "usage limit"),
        ({"is_error": None}, "no result"),
        ({"is_error": True}, "error"),
        ({"exit_code": 1}, "exit code 1"),
    ],
)
def test_a_run_is_set_aside_only_when_it_did_not_finish(
    changes: dict[str, Any], reason: str | None
) -> None:
    assert ra.set_aside_reason(record(**changes)) == reason


def index_of(out: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]


def test_a_failed_run_is_set_aside_and_its_slot_runs_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    done, calls = fake_batch(monkeypatch, tmp_path, [record(), record(is_error=True)])
    assert done == 2 and calls == [("p01", "A"), ("p01", "B")]
    failed = index_of(tmp_path)[1]
    assert failed["set_aside"] == "error" and failed["transcript"] == "m/B/p01-r1.failed-1.jsonl"
    assert (tmp_path / failed["transcript"]).is_file()
    assert not (tmp_path / "m" / "B" / "p01-r1.jsonl").exists()
    # Started again, the batch runs that slot again; a second failure keeps the first.
    done, calls = fake_batch(monkeypatch, tmp_path, [record(is_error=True)])
    assert calls == [("p01", "B")]
    assert index_of(tmp_path)[2]["transcript"] == "m/B/p01-r1.failed-2.jsonl"
    assert (tmp_path / "m" / "B" / "p01-r1.failed-1.jsonl").is_file()
    done, calls = fake_batch(monkeypatch, tmp_path, [record()] * 3)
    assert calls == [("p01", "B"), ("p02", "A"), ("p02", "B")]
    assert "set_aside" not in index_of(tmp_path)[3]


def test_a_timed_out_run_counts_and_is_not_run_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    timed_out = record(timed_out=True, is_error=None, exit_code=-9, final=None)
    done, calls = fake_batch(monkeypatch, tmp_path, [timed_out])
    assert done == 1 and calls == [("p01", "A")]
    first = index_of(tmp_path)[0]
    assert "set_aside" not in first and first["transcript"] == "m/A/p01-r1.jsonl"
    done, calls = fake_batch(monkeypatch, tmp_path, [record()] * 3)
    assert calls == [("p01", "B"), ("p02", "A"), ("p02", "B")]


def test_keep_going_runs_on_past_a_timeout_but_not_past_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    timed_out = record(timed_out=True, is_error=None, exit_code=-9, final=None)
    calls: list[str] = []

    def run_one(
        bundle: Path, condition: str, model: str, transcript: Path, server: Any = None
    ) -> dict[str, Any]:
        calls.append(f"{bundle.name} {condition}")
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("{}\n")
        return {**[timed_out, record(), record(is_error=True), record()][len(calls) - 1]}

    monkeypatch.setattr(ra, "run_one", run_one)
    monkeypatch.setattr(ra, "git_head", lambda: "abc123")
    monkeypatch.setattr(ra, "token_seconds_left", lambda: 10 * 3600.0)
    bundles = [EVAL / "pilot" / "bundles" / "p01", EVAL / "pilot" / "bundles" / "p02"]
    done = ra.run_batch(bundles, ["A", "B"], 1, "m", tmp_path, keep_going=True)
    assert done == 3 and calls == ["p01 A", "p01 B", "p02 A"]
    assert index_of(tmp_path)[2]["set_aside"] == "error"


def test_scored_runs_need_committed_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def which(name: str) -> str:
        return f"/usr/bin/{name}"

    monkeypatch.setattr(ra, "git_head", lambda: "abc123-dirty")
    monkeypatch.setattr(ra.shutil, "which", which)
    with pytest.raises(SystemExit) as stop:
        ra.main(["--bundles", "b01"])
    assert stop.value.code == 2 and "commit first" in capsys.readouterr().err


def test_a_batch_will_not_start_a_run_the_login_could_expire_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    done, calls = fake_batch(monkeypatch, tmp_path, [record()], token_s=ra.TIMEOUT_S)
    assert done == 0 and calls == []


def test_summarise_counts_compactions(tmp_path: Path) -> None:
    transcript = tmp_path / "t.jsonl"
    events = [
        {"type": "system", "subtype": "init"},
        {"type": "system", "subtype": "compact_boundary"},
        {"type": "result", "is_error": False, "result": "x"},
    ]
    transcript.write_text("".join(json.dumps(e) + "\n" for e in events))
    assert ra.summarise(transcript).compactions == 1


def test_progress_events_are_dropped_and_counted(tmp_path: Path) -> None:
    transcript = tmp_path / "t.jsonl"
    events = [
        {"type": "system", "subtype": "init"},
        {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 1},
        {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 2},
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "hm"}]}},
        {"type": "result", "is_error": False, "result": "x"},
    ]
    transcript.write_text("".join(json.dumps(e) + "\n" for e in events) + "not json\n")
    assert ra.drop_progress(transcript) == 2
    kept = transcript.read_text().splitlines()
    assert kept[-1] == "not json"
    assert [json.loads(line)["type"] for line in kept[:-1]] == ["system", "assistant", "result"]
    assert ra.drop_progress(transcript) == 0


def test_the_home_folder_is_written_as_home_user(tmp_path: Path) -> None:
    transcript = tmp_path / "t.jsonl"
    saved = f"Output too large. Full output saved to: {Path.home()}/.claude/projects/-study/x.txt"
    transcript.write_text(json.dumps({"type": "user", "content": saved}) + "\n")
    assert ra.rename_home(transcript) == 1
    text = transcript.read_text()
    assert "/home/user/.claude/projects/-study/x.txt" in text and str(Path.home()) not in text
    assert ra.rename_home(transcript) == 0


# --- a local model ---------------------------------------------------------------------------

PROPS: dict[str, Any] = {
    "build_info": "b11678-b6334e37e",
    "model_path": "/models/qwen/Qwen3.8-27B-UD-Q6_K.gguf",
    "model_alias": "qwen-local",
    "total_slots": 1,
    "default_generation_settings": {
        "n_ctx": 118784,
        "params": {
            "temperature": 0.699999988079071,
            "top_k": 20,
            "top_p": 0.800000011920929,
            "min_p": 0.0,
        },
    },
}


PROCESS = {"command": ["~/llama-server", "--port", "8094"], "env": ["GGML_VK_DISABLE_COOPMAT2=1"]}


def local(**changes: Any) -> Any:
    record = {**ra.describe(PROPS), **PROCESS, "model_sha256": "f" * 64, **changes}
    return ra.Server("http://127.0.0.1:8094", record)


def same_process(url: str) -> dict[str, list[str]]:
    return PROCESS


def test_a_server_is_recorded_by_its_model_file_s_hash_not_its_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weights = tmp_path / "Qwen3.8-27B-UD-Q6_K.gguf"
    weights.write_bytes(b"weights")
    asked: list[str] = []

    def server_props(url: str) -> dict[str, Any]:
        asked.append(url)
        return {**PROPS, "model_path": str(weights)}

    monkeypatch.setattr(ra, "server_props", server_props)
    monkeypatch.setattr(ra, "server_process", same_process)
    server = ra.local_server("http://127.0.0.1:8094/", "qwen-local")
    assert server.url == "http://127.0.0.1:8094" and asked == ["http://127.0.0.1:8094"]
    assert server.record == {
        "build": "b11678-b6334e37e",
        "model_file": "Qwen3.8-27B-UD-Q6_K.gguf",
        "model_alias": "qwen-local",
        "n_ctx": 118784,
        "slots": 1,
        "sampling": {"temperature": 0.7, "top_k": 20, "top_p": 0.8, "min_p": 0.0},
        **PROCESS,
        "model_sha256": hashlib.sha256(b"weights").hexdigest(),
    }
    assert str(tmp_path) not in json.dumps(server.record)
    with pytest.raises(SystemExit, match="serves 'qwen-local', not 'other'"):
        ra.local_server("http://127.0.0.1:8094", "other")


def test_a_local_model_gets_its_server_and_no_login(tmp_path: Path) -> None:
    server = local()
    env = ra.environment(server)
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8094"
    assert env["ANTHROPIC_AUTH_TOKEN"] == ra.LOCAL_TOKEN
    assert env["ANTHROPIC_SMALL_FAST_MODEL"] == env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "qwen-local"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "118784"
    assert env["API_TIMEOUT_MS"] == str(ra.TIMEOUT_S * 1000)
    assert env["CLAUDE_CODE_MODEL_CAPABILITIES"] == "qwen-local=-mid_conv_system"
    assert ra.environment().items() <= env.items()
    argv = ra.sandbox(["claude"], tmp_path, CLAUDE, server=True, local=server)
    assert str(ra.CREDENTIALS) not in binds(argv)
    assert {argv[i + 1]: argv[i + 2] for i, a in enumerate(argv) if a == "--setenv"} == env
    # Claude's runs keep the login file and get none of the local settings.
    claude = ra.sandbox(["claude"], tmp_path, CLAUDE, server=True)
    assert binds(claude)[str(ra.CREDENTIALS)] == str(ra.CREDENTIALS)
    local_only = ("ANTHROPIC_", "API_TIMEOUT", "CLAUDE_CODE_MAX", "CLAUDE_CODE_MODEL")
    assert not [a for a in claude if a.startswith(local_only)]


def test_the_server_must_answer_as_it_did_when_the_batch_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = local()
    answers = iter([PROPS, {**PROPS, "default_generation_settings": {"n_ctx": 65536}}])

    def server_props(url: str) -> dict[str, Any]:
        return next(answers)

    monkeypatch.setattr(ra, "server_props", server_props)
    monkeypatch.setattr(ra, "server_process", same_process)
    assert ra.server_problem(server) is None
    assert "does not answer" in (ra.server_problem(server) or "")  # no params: not llama-server
    settings = {**PROPS["default_generation_settings"], "n_ctx": 65536}
    answers = iter([{**PROPS, "default_generation_settings": settings}])
    assert "has changed" in (ra.server_problem(server) or "")

    def gone(url: str) -> dict[str, Any]:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(ra, "server_props", gone)
    assert "does not answer" in (ra.server_problem(server) or "")

    def restarted(url: str) -> dict[str, list[str]]:
        return {**PROCESS, "command": [*PROCESS["command"], "--reasoning-budget", "0"]}

    def props(url: str) -> dict[str, Any]:
        return PROPS

    monkeypatch.setattr(ra, "server_props", props)
    monkeypatch.setattr(ra, "server_process", restarted)
    assert "has changed" in (ra.server_problem(server) or "")


@pytest.mark.skipif(sys.platform != "linux" or ra.shutil.which("ss") is None, reason="needs ss")
def test_the_server_process_is_found_by_its_port() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        found = ra.server_process(f"http://127.0.0.1:{port}")
    own = Path(f"/proc/{os.getpid()}/cmdline").read_bytes().decode().split("\0")
    home = str(Path.home())
    assert found["command"] == [arg.replace(home, "~") for arg in own if arg]
    assert all(s.startswith(("GGML_", "LLAMA_")) for s in found["env"])
    with pytest.raises(SystemExit, match="no single local process"):
        ra.server_process(f"http://127.0.0.1:{port}")


def test_a_local_batch_reads_no_login_and_stops_when_the_server_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = local()
    given: list[Any] = []
    problems = iter([None, None, "the server at http://127.0.0.1:8094 does not answer"])

    def run_one(
        bundle: Path, condition: str, model: str, transcript: Path, server: Any = None
    ) -> dict[str, Any]:
        given.append(server)
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("{}\n")
        return {**record(), "condition": condition}

    def no_login() -> float:
        raise AssertionError("a local model's batch reads no login")

    monkeypatch.setattr(ra, "run_one", run_one)
    monkeypatch.setattr(ra, "git_head", lambda: "abc123")
    monkeypatch.setattr(ra, "token_seconds_left", no_login)

    def server_problem(s: Any) -> str | None:
        return next(problems)

    monkeypatch.setattr(ra, "server_problem", server_problem)
    bundles = [EVAL / "pilot" / "bundles" / "p01", EVAL / "pilot" / "bundles" / "p02"]
    done = ra.run_batch(bundles, ["A", "B"], 1, "qwen-local", tmp_path, server)
    assert done == 2 and given == [server, server]


def test_a_local_model_must_be_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def which(name: str) -> str:
        return f"/usr/bin/{name}"

    monkeypatch.setattr(ra.shutil, "which", which)
    with pytest.raises(SystemExit) as stop:
        ra.main(["--server", "http://127.0.0.1:8094", "--bundles", "b01"])
    assert stop.value.code == 2 and "--model" in capsys.readouterr().err
