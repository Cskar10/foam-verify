"""The agent harness (eval/run_agents.py) without running an agent: the prompt, the command,
the sandbox it runs in, and how a batch reads transcripts and decides to stop."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
import tomllib
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


def record(**changes: Any) -> dict[str, Any]:
    base = {
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

    def run_one(bundle: Path, condition: str, model: str, transcript: Path) -> dict[str, Any]:
        calls.append((bundle.name, condition))
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("{}\n")
        return records[len(calls) - 1]

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
