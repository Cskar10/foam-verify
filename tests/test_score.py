"""The scorer (eval/score.py): its rules on hand-written answers, its protocol checks on made-up
transcripts, and its scores of the pilot's committed transcripts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
PILOT_RUNS = EVAL / "pilot" / "runs"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EVAL / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


ra = sys.modules.get("run_agents") or load("run_agents")
sc = load("score")
LABELS = sc.load_labels(sc.LABELS, sc.LABELS_SHA256)
DUCT_EXACT = 56.90830753911475


# --- the labels -----------------------------------------------------------------------------


def test_the_labels_are_the_committed_ones() -> None:
    data = (EVAL / "labels.toml").read_bytes()
    assert hashlib.sha256(data).hexdigest() == sc.LABELS_SHA256
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("no git history here (a clean export): the hash check above stands alone")
    committed = subprocess.run(
        [git, "-C", str(ROOT), "show", f"{sc.LABELS_COMMIT}:eval/labels.toml"],
        capture_output=True,
        check=True,
    ).stdout
    assert committed == data


def test_the_scorer_refuses_other_labels(tmp_path: Path) -> None:
    changed = tmp_path / "labels.toml"
    changed.write_text((EVAL / "labels.toml").read_text().replace('"b06"', '"b13"'))
    with pytest.raises(sc.ScoreError, match="not the labels file committed at 90d5c4f"):
        sc.load_labels(changed, sc.LABELS_SHA256)


def test_the_labels_load_as_committed() -> None:
    assert sorted(LABELS) == [f"b{n:02d}" for n in range(1, 13)]
    sound = sorted(i for i, label in LABELS.items() if label.verdict == "trustworthy")
    assert sound == ["b06", "b07", "b09", "b11"]
    assert sorted(i for i, label in LABELS.items() if label.exact is not None) == [
        "b02",
        "b03",
        "b06",
        "b11",
    ]
    assert {LABELS[i].exact for i in ("b02", "b03", "b06", "b11")} == {DUCT_EXACT}
    assert (LABELS["b06"].value, LABELS["b06"].uncertainty) == (56.8997, 0.0108)
    assert LABELS["b12"].reasons == ("iterative", "grid_convergence")


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ('verdict = "fine"\nreasons = []', "unknown verdict"),
        ('verdict = "not_trustworthy"\nreasons = ["luck"]', "unknown reason"),
        ('verdict = "not_trustworthy"\nreasons = []', "reasons go with not_trustworthy"),
        ('verdict = "trustworthy"\nreasons = []', "needs its value and U"),
    ],
)
def test_a_malformed_label_is_refused(entry: str, message: str, tmp_path: Path) -> None:
    path = tmp_path / "labels.toml"
    path.write_text(f'[[bundle]]\nid = "x1"\nqoi = "q"\n{entry}\n')
    with pytest.raises(sc.ScoreError, match=message):
        sc.load_labels(path)


# --- the answer line ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "converged", "value", "uncertainty"),
    [
        ("FINAL: converged=yes; value=-0.21376; uncertainty=0.00037", "yes", -0.21376, 0.00037),
        ("**FINAL: converged=no; value=6.84; uncertainty=none**", "no", 6.84, None),
        ("FINAL: converged=YES; value=56.8997 (f Re); uncertainty=±0.0108", "yes", 56.8997, 0.0108),
        ("FINAL: converged=yes; value=−0.2089; uncertainty=1.6e-3", "yes", -0.2089, 0.0016),
        ("FINAL: converged=yes; value=0.1794; uncertainty=2.6×10⁻⁴", "yes", 0.1794, 0.00026),
        ("FINAL: converged=yes; value=0.1794; uncertainty=2.6 x 10^-4", "yes", 0.1794, 0.00026),
        ("FINAL: converged=yes; value=50; uncertainty=0.02%", "yes", 50.0, 0.01),
        ("FINAL: converged=no (two grids only); value=56.9; uncertainty=n/a", "no", 56.9, None),
        ("FINAL: converged=yes, value=0.17937, uncertainty=+/- 0.00026", "yes", 0.17937, 0.00026),
        ("`FINAL: converged=yes; value=1; uncertainty=0.1`", "yes", 1.0, 0.1),
        ("FINAL: converged: no; value: none; uncertainty: none", "no", None, None),
        ("FINAL: converged=yes; value=~56.9; uncertainty=-0.01", "yes", 56.9, 0.01),
        ("FINAL: converged=no; value=-; uncertainty=—", "no", None, None),
    ],
)
def test_the_answer_line_is_read(
    line: str, converged: str, value: float | None, uncertainty: float | None
) -> None:
    answer = sc.parse_final(line)
    assert answer.converged == converged
    assert answer.value == (None if value is None else pytest.approx(value))
    assert answer.uncertainty == (None if uncertainty is None else pytest.approx(uncertainty))
    assert answer.notes == ()


@pytest.mark.parametrize(
    ("line", "note"),
    [
        (None, "no FINAL line"),
        ("FINAL: converged=<yes|no>; value=<number|none>; uncertainty=<number|none>", "not yes"),
        ("FINAL: converged=maybe; value=1; uncertainty=0.1", "not yes or no"),
        ("FINAL: converged=yes/no; value=1; uncertainty=0.1", "not yes or no"),
        ("FINAL: converged=true; value=1; uncertainty=0.1", "not yes or no"),
        ("FINAL: value=1; uncertainty=0.1", "no converged="),
    ],
)
def test_an_answer_without_yes_or_no_has_no_verdict(line: str | None, note: str) -> None:
    answer = sc.parse_final(line)
    assert answer.converged is None
    assert any(note in n for n in answer.notes), answer.notes
    label = LABELS["b02"]  # not trustworthy: no verdict is neither right nor false trust
    scored = sc.score(label, answer)
    assert scored["verdict"] is None and not scored["correct"] and not scored["false_trust"]


def test_numbers_the_scorer_cannot_read_are_none_with_a_note() -> None:
    answer = sc.parse_final("FINAL: converged=yes; value=about fifty; uncertainty=small")
    assert (answer.converged, answer.value, answer.uncertainty) == ("yes", None, None)
    assert answer.notes == (
        "value not a number: 'about fifty'",
        "uncertainty not a number: 'small'",
    )
    percent = sc.parse_final("FINAL: converged=no; value=none; uncertainty=5%")
    assert percent.uncertainty is None and percent.notes == ("uncertainty in % of no value",)


def test_the_answer_line_is_the_last_one_that_names_converged() -> None:
    answer = (
        "I was asked to end with FINAL: converged=<yes|no>; value=<number|none>; ...\n"
        "> FINAL: converged=no; value=56.9; uncertainty=none\n"
        "Final thoughts: the duct is a smooth case.\n"
        "- **FINAL: converged=yes; value=56.8997; uncertainty=0.0108**\n"
        "Final: that is all.\n"
    )
    line = ra.final_line(answer)
    assert line == "- **FINAL: converged=yes; value=56.8997; uncertainty=0.0108**"
    assert sc.parse_final(line).converged == "yes"


# --- scoring one answer ---------------------------------------------------------------------


def answer(converged: str | None, value: float | None = None, u: float | None = None) -> Any:
    return sc.Answer("FINAL: ...", converged, value, u)


@pytest.mark.parametrize(
    ("bundle", "converged", "correct", "false_trust", "missed_trust"),
    [
        ("b06", "yes", True, False, False),
        ("b06", "no", False, False, True),
        ("b02", "no", True, False, False),
        ("b02", "yes", False, True, False),
        ("b03", "yes", False, True, False),  # accurate, but r = 1.1: still false trust
        ("b06", None, False, False, False),
    ],
)
def test_verdicts_against_the_label(
    bundle: str, converged: str | None, correct: bool, false_trust: bool, missed_trust: bool
) -> None:
    scored = sc.score(LABELS[bundle], answer(converged))
    assert (scored["correct"], scored["false_trust"], scored["missed_trust"]) == (
        correct,
        false_trust,
        missed_trust,
    )


def test_a_duct_band_is_checked_against_the_exact_value_whatever_the_verdict() -> None:
    inside = sc.score(LABELS["b06"], answer("yes", 56.8997, 0.0108))
    assert inside["band_holds_exact"] is True and inside["in_label_band"] is True
    assert inside["u_ratio"] == pytest.approx(1.0)
    outside = sc.score(LABELS["b06"], answer("yes", 56.8997, 0.005))
    assert outside["band_holds_exact"] is False and outside["in_label_band"] is True
    # A two-grid estimate with its caveat: right verdict, and its band is still checked.
    caveated = sc.score(LABELS["b02"], answer("no", 56.90, 0.03))
    assert caveated["correct"] and caveated["band_holds_exact"] is True
    assert caveated["in_label_band"] is None  # b02 has no label value
    # No band without both numbers; no exact value on a cavity bundle.
    assert sc.score(LABELS["b06"], answer("yes", 56.9))["band_holds_exact"] is None
    assert sc.score(LABELS["b07"], answer("yes", -0.2089, 0.0003))["band_holds_exact"] is None


def test_a_band_edge_holds() -> None:
    label = sc.Label("x", "q", "not_trustworthy", ("two_grids",), exact=1.0)
    assert sc.score(label, answer("no", 0.5, 0.5))["band_holds_exact"] is True
    assert sc.score(label, answer("no", 0.5, 0.25))["band_holds_exact"] is False


def test_a_sound_bundle_s_value_is_checked_against_the_label_s_band() -> None:
    near = sc.score(LABELS["b09"], answer("yes", 0.1795, 0.0003))
    assert near["in_label_band"] is True and near["u_ratio"] == pytest.approx(0.0003 / 0.000257)
    far = sc.score(LABELS["b09"], answer("yes", 0.1810, 0.0003))
    assert far["in_label_band"] is False


def test_percentages_round_half_up_and_come_with_their_counts() -> None:
    assert sc.percent(3, 24) == "3 of 24 (13%)"
    assert sc.percent(1, 8) == "1 of 8 (13%)"
    assert sc.percent(0, 12) == "0 of 12 (0%)"
    assert sc.percent(36, 36) == "36 of 36 (100%)"
    assert sc.percent(0, 0) == "-"


# --- scoring runs, from made-up transcripts -------------------------------------------------

TOOLS_A = ["Glob", "Grep", "Read"]
TOOLS_B = [*TOOLS_A, "mcp__foam-verify__verification_report", "mcp__foam-verify__study_summary"]
CONNECTED = [{"name": "foam-verify", "status": "connected", "source": "dynamic"}]


def init(condition: str, **changes: Any) -> dict[str, Any]:
    base = {
        "type": "system",
        "subtype": "init",
        "cwd": "/study",
        "model": "m",
        "tools": TOOLS_A if condition == "A" else TOOLS_B,
        "mcp_servers": [] if condition == "A" else CONNECTED,
    }
    return {**base, **changes}


def result(text: str, *, error: bool = False) -> dict[str, Any]:
    return {"type": "result", "subtype": "success", "is_error": error, "result": text}


class Runs:
    """A runs folder as the harness writes it."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.index = out / "runs.jsonl"

    def add(
        self,
        bundle: str,
        condition: str,
        run: int,
        events: list[dict[str, Any]],
        **changes: Any,
    ) -> dict[str, Any]:
        name = f"m/{condition}/{bundle}-r{run}.jsonl"
        path = self.out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
        summary = ra.summarise(path)
        first: dict[str, Any] = summary.init or {}
        record: dict[str, Any] = {
            "run": run,
            "foam_verify": "abc123",
            "transcript": name,
            "bundle": bundle,
            "condition": condition,
            "model": "m",
            "duration_s": 10.0,
            "exit_code": 0,
            "timed_out": False,
            "unchanged": True,
            "cwd": first.get("cwd"),
            "tools": first.get("tools"),
            "mcp_servers": first.get("mcp_servers"),
            "is_error": None if summary.result is None else summary.result.get("is_error"),
            "num_turns": 2,
            "total_cost_usd": 0.05,
            "permission_denials": 0,
            "final": ra.final_line(summary.answer),
            "hit_limit": summary.hit_limit,
            **changes,
        }
        if ra.set_aside_reason(record) is not None and "set_aside" not in changes:
            record["set_aside"] = ra.set_aside_reason(record)
            moved = ra.set_aside(path)
            record["transcript"] = str(moved.relative_to(self.out))
        with self.index.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        return record


YES_DUCT = "Converged.\nFINAL: converged=yes; value=56.8997; uncertainty=0.0108"
NO = "Two grids only.\nFINAL: converged=no; value=56.90; uncertainty=none"


def test_runs_are_scored_and_tabled(tmp_path: Path) -> None:
    runs = Runs(tmp_path)
    for k in (1, 2, 3):
        runs.add("b06", "A", k, [init("A"), result(YES_DUCT)])
        runs.add("b06", "B", k, [init("B"), result(YES_DUCT)])
        runs.add("b02", "A", k, [init("A"), result(YES_DUCT if k == 1 else NO)])
        runs.add("b02", "B", k, [init("B"), result(NO)])
    rows = sc.score_runs(tmp_path, LABELS, clean=True)
    assert len(rows) == 12 and {r["status"] for r in rows} == {"finished"}
    a, b = sc.counts(rows, "m", "A"), sc.counts(rows, "m", "B")
    assert (a["runs"], a["correct"], a["false_trust"], a["broken_runs"]) == (6, 5, 1, 3)
    assert (b["runs"], b["correct"], b["false_trust"], b["missed_trust"]) == (6, 6, 0, 0)
    # The duct bands: b06's six and b02's one, all holding the exact value.
    assert (a["bands_holding_exact"], a["bands_stated"]) == (4, 4)
    assert (b["bands_holding_exact"], b["bands_stated"]) == (3, 3)
    text = sc.markdown(rows, LABELS, "the labels")
    assert "| m | A | 6 | 5 of 6 (83%) | 1 of 3 (33%) | 0 of 3 (0%) | 0 | 4 of 4 |" in text
    assert "| m | B | 6 | 6 of 6 (100%) | 0 of 3 (0%) | 0 of 3 (0%) | 0 | 3 of 3 |" in text
    assert "| b02 | not trustworthy | two_grids | yes no no (2 of 3) | no no no (3 of 3) |" in text
    assert "| b06 | 56.8997 ± 0.0108; exact 56.9083 | 1 | 56.8997 ± 0.0108 (holds exact" in text
    assert "| b01 | not trustworthy | iterative |  |  |" in text  # no runs yet: empty cells


def test_a_run_that_did_not_finish_is_set_aside_and_its_slot_run_again(tmp_path: Path) -> None:
    runs = Runs(tmp_path)
    limited = runs.add(
        "b06", "A", 1, [init("A"), result("You've hit your limit", error=True)], hit_limit=True
    )
    assert limited["set_aside"] == "usage limit"
    assert limited["transcript"] == "m/A/b06-r1.failed-1.jsonl"
    runs.add("b06", "A", 1, [init("A"), result(YES_DUCT)])
    unconnected = [{"name": "foam-verify", "status": "failed"}]
    runs.add("b06", "B", 1, [init("B", mcp_servers=unconnected), result(YES_DUCT)])
    runs.add("b06", "B", 1, [init("B"), result(YES_DUCT)])
    rows = sc.score_runs(tmp_path, LABELS, clean=True)
    assert [(r["status"], r.get("reason")) for r in rows] == [
        ("set_aside", "usage limit"),
        ("finished", None),
        ("set_aside", "foam-verify not connected"),
        ("finished", None),
    ]
    assert sc.counts(rows, "m", "B")["set_aside"] == 1
    text = sc.markdown(rows, LABELS, "the labels")
    assert "| m | A | b06 | 1 | usage limit | `m/A/b06-r1.failed-1.jsonl` |" in text


def test_a_timed_out_run_counts_as_an_answer_without_a_verdict(tmp_path: Path) -> None:
    runs = Runs(tmp_path)
    runs.add("b06", "A", 1, [init("A")], timed_out=True, exit_code=-9)
    rows = sc.score_runs(tmp_path, LABELS, clean=True)
    assert rows[0]["status"] == "timed_out" and rows[0]["verdict"] is None
    assert not rows[0]["correct"] and rows[0]["notes"] == ["no FINAL line"]
    assert sc.counts(rows, "m", "A")["timed_out"] == 1


def test_a_run_marked_against_the_rule_is_refused(tmp_path: Path) -> None:
    Runs(tmp_path).add("b06", "A", 1, [init("A"), result(YES_DUCT)], set_aside="error")
    with pytest.raises(sc.ScoreError, match="by the rule it is None"):
        sc.score_runs(tmp_path, LABELS, clean=True)


@pytest.mark.parametrize(
    ("condition", "first", "changes", "message"),
    [
        ("A", {"cwd": "/home/x"}, {}, "working folder"),
        ("A", {"model": "other"}, {}, "model 'other'"),
        ("A", {"tools": [*TOOLS_A, "Bash"]}, {}, "condition A with tools"),
        ("A", {"mcp_servers": CONNECTED}, {}, "condition A with tools"),
        ("B", {"tools": TOOLS_A}, {}, "condition B with tools"),
        ("B", {"tools": [*TOOLS_A, "mcp__other__x"]}, {}, "condition B with tools"),
        ("A", {}, {"unchanged": False}, "copy changed"),
        ("A", {}, {"foam_verify": "abc123-dirty"}, "uncommitted code"),
    ],
)
def test_a_run_that_broke_the_protocol_is_refused(
    condition: str, first: dict[str, Any], changes: dict[str, Any], message: str, tmp_path: Path
) -> None:
    Runs(tmp_path).add("b06", condition, 1, [init(condition, **first), result(YES_DUCT)], **changes)
    with pytest.raises(sc.ScoreError, match=message):
        sc.score_runs(tmp_path, LABELS, clean=True)


def test_the_pilot_may_be_scored_from_a_working_tree(tmp_path: Path) -> None:
    Runs(tmp_path).add("b06", "A", 1, [init("A"), result(YES_DUCT)], foam_verify="abc-dirty")
    assert sc.score_runs(tmp_path, LABELS, clean=False)[0]["correct"]


def test_two_runs_for_one_slot_are_refused(tmp_path: Path) -> None:
    runs = Runs(tmp_path)
    runs.add("b06", "A", 1, [init("A"), result(YES_DUCT)])
    second = runs.add("b06", "A", 2, [init("A"), result(YES_DUCT)])
    lines = runs.index.read_text().splitlines()
    second["run"] = 1
    runs.index.write_text("\n".join([lines[0], json.dumps(second)]) + "\n")
    with pytest.raises(sc.ScoreError, match="a second run that counts"):
        sc.score_runs(tmp_path, LABELS, clean=True)


def test_an_index_that_disagrees_with_its_transcript_is_refused(tmp_path: Path) -> None:
    Runs(tmp_path).add("b06", "A", 1, [init("A"), result(YES_DUCT)], final="FINAL: converged=no")
    with pytest.raises(sc.ScoreError, match="not the transcript's"):
        sc.score_runs(tmp_path, LABELS, clean=True)


def test_an_unknown_bundle_or_a_missing_transcript_is_refused(tmp_path: Path) -> None:
    runs = Runs(tmp_path)
    runs.add("b99", "A", 1, [init("A"), result(YES_DUCT)])
    with pytest.raises(sc.ScoreError, match="no label for bundle 'b99'"):
        sc.score_runs(tmp_path, LABELS, clean=True)
    runs.index.unlink()
    runs.add("b06", "A", 1, [init("A"), result(YES_DUCT)])
    (tmp_path / "m" / "A" / "b06-r1.jsonl").unlink()
    with pytest.raises(sc.ScoreError, match="transcript missing"):
        sc.score_runs(tmp_path, LABELS, clean=True)
    with pytest.raises(sc.ScoreError, match="no runs.jsonl"):
        sc.score_runs(tmp_path / "nowhere", LABELS, clean=True)


# --- the pilot ------------------------------------------------------------------------------


def test_the_pilot_scores_as_committed(tmp_path: Path) -> None:
    labels = sc.load_labels(sc.PILOT_LABELS)
    rows = sc.score_runs(PILOT_RUNS, labels, clean=False)
    assert [(r["bundle"], r["condition"], r["verdict"], r["correct"]) for r in rows] == [
        ("p01", "A", "trustworthy", True),
        ("p01", "B", "trustworthy", True),
        ("p02", "A", "not_trustworthy", True),
        ("p02", "B", "not_trustworthy", True),
    ]
    assert [r["value"] for r in rows] == [-0.21376, -0.21376, 6.84, 6.837916]
    assert [r["uncertainty"] for r in rows] == [0.00037, 0.000366, None, None]
    assert all(r["in_label_band"] for r in rows if r["bundle"] == "p01")
    # The committed scores are what the scorer writes now.
    copy = tmp_path / "runs"
    shutil.copytree(PILOT_RUNS, copy)
    assert sc.main(["--pilot", "--runs", str(copy)]) == 0
    for name in ("scores.jsonl", "scores.md"):
        assert (copy / name).read_text() == (PILOT_RUNS / name).read_text(), name


def test_the_command_line_refuses_what_it_cannot_score(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sc.main(["--runs", str(tmp_path)]) == 2
    assert "no runs.jsonl" in capsys.readouterr().err
