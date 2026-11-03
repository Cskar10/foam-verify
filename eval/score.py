"""Score the agents' answers against the labels.

    python3 eval/score.py            # the evaluation: eval/runs/, against eval/labels.toml
    python3 eval/score.py --pilot    # the pilot: eval/pilot/runs/, against eval/pilot/labels.toml

Reads runs.jsonl and every transcript it lists, checks each run against the protocol, and writes
scores.jsonl (one line per run) and scores.md (the tables) beside them. The rules were fixed before
any scored run, as the labels were, and are the same for every model and condition; eval/README.md
(Scoring) gives them in full. In short: the verdict is read from the answer's FINAL line alone,
converged=yes being the verdict trustworthy; false trust is that verdict on a bundle labelled
not_trustworthy; and wherever a label has an exact value (the duct's f Re), the scorer records
whether the band an answer states holds it. Whether an answer names a label's reasons is not
scored here: that takes reading, and every transcript is committed for it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from run_agents import CONDITIONS, SERVER, STUDY, TOOLS, final_line, set_aside_reason, summarise

HERE = Path(__file__).resolve().parent
LABELS = HERE / "labels.toml"
# The labels committed before any bundle was built; the scorer refuses any other labels file.
LABELS_COMMIT = "90d5c4fa5f0d56557ff74a99672a3dd185aaa60e"
LABELS_SHA256 = "0b5fbcccc5702db1138772c271733ec3fe3909e35acf8f8501296dc2dcc2b60d"
PILOT_LABELS = HERE / "pilot" / "labels.toml"
VERDICTS = ("trustworthy", "not_trustworthy")
REASONS = ("iterative", "two_grids", "refinement_ratio", "settings", "grid_convergence")


class ScoreError(Exception):
    """A labels file, index or run that the scorer will not score."""


# --- labels ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Label:
    id: str
    qoi: str
    verdict: str
    reasons: tuple[str, ...]
    value: float | None = None
    uncertainty: float | None = None
    exact: float | None = None


def _optional(entry: dict[str, Any], key: str) -> float | None:
    return None if key not in entry else float(entry[key])


def load_labels(path: Path, sha256: str | None = None) -> dict[str, Label]:
    """The labels by bundle id. With sha256, the file must have that hash."""
    data = path.read_bytes()
    if sha256 is not None and hashlib.sha256(data).hexdigest() != sha256:
        raise ScoreError(
            f"{path.name} is not the labels file committed at {LABELS_COMMIT[:7]}: its sha256 "
            "differs, and the labels do not change after that commit"
        )
    labels: dict[str, Label] = {}
    for entry in tomllib.loads(data.decode("utf-8"))["bundle"]:
        label = Label(
            id=str(entry["id"]),
            qoi=str(entry["qoi"]),
            verdict=str(entry["verdict"]),
            reasons=tuple(str(reason) for reason in entry["reasons"]),
            value=_optional(entry, "value"),
            uncertainty=_optional(entry, "uncertainty"),
            exact=_optional(entry, "exact"),
        )
        if label.id in labels:
            raise ScoreError(f"{path.name}: two labels for {label.id}")
        if label.verdict not in VERDICTS:
            raise ScoreError(f"{path.name}: {label.id}: unknown verdict {label.verdict!r}")
        if any(reason not in REASONS for reason in label.reasons):
            raise ScoreError(f"{path.name}: {label.id}: unknown reason in {label.reasons}")
        if (label.verdict == "trustworthy") == bool(label.reasons):
            raise ScoreError(f"{path.name}: {label.id}: reasons go with not_trustworthy only")
        if label.verdict == "trustworthy" and (label.value is None or label.uncertainty is None):
            raise ScoreError(f"{path.name}: {label.id}: a trustworthy label needs its value and U")
        labels[label.id] = label
    return labels


# --- the answer line ------------------------------------------------------------------------

_FIELD = {
    key: re.compile(rf"(?<![a-z_]){key}\s*[=:]\s*([^;,\n]*)", re.IGNORECASE)
    for key in ("converged", "value", "uncertainty")
}
_WORD = re.compile(r"(yes|no)\b(?!\s*[/|])")
_NONE = re.compile(r"(?:none|n/?a\b|null|unknown|undefined|not\b|nan\b|-+$|—)", re.IGNORECASE)
_PREFIX = re.compile(r"^(?:±|\+/-|\+-|~|≈|about\s)\s*", re.IGNORECASE)
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?", re.IGNORECASE)
_TIMES_TEN = re.compile(r"\s*[x×]\s*10\s*\^?\s*([+-]?\d+)")
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
_MARKS = " \t*`_"


@dataclass(frozen=True)
class Answer:
    """An answer's FINAL line as the scorer reads it."""

    line: str | None
    converged: str | None  # "yes", "no", or None: no verdict
    value: float | None
    uncertainty: float | None
    notes: tuple[str, ...] = ()


def _field(line: str, key: str) -> str | None:
    found = _FIELD[key].search(line)
    return None if found is None else found.group(1).strip(_MARKS)


def _number(text: str) -> tuple[float | None, bool, str | None]:
    """A field's number, whether a % follows it, and a note if the field is neither a number nor
    none. The number may start with a plus-minus sign, +/-, ~ or an almost-equal sign, and use a
    Unicode minus and an exponent (e-4, x10^-4 or a superscript one)."""
    clean = _PREFIX.sub("", text.replace("−", "-").translate(_SUPERSCRIPT).strip())
    if not clean or _NONE.match(clean):
        return None, False, None
    found = _NUMBER.match(clean)
    if found is None:
        return None, False, f"not a number: {text!r}"
    number = float(found.group())
    rest = clean[found.end() :]
    times = _TIMES_TEN.match(rest)
    if times is not None:
        number *= 10.0 ** int(times.group(1))
        rest = rest[times.end() :]
    if not math.isfinite(number):
        return None, False, f"not a finite number: {text!r}"
    return number, rest.lstrip().startswith("%"), None


def _read(line: str, key: str, notes: list[str]) -> tuple[float | None, bool]:
    text = _field(line, key)
    if text is None:
        notes.append(f"no {key}=")
        return None, False
    number, percent, note = _number(text)
    if note is not None:
        notes.append(f"{key} {note}")
    return number, percent


def parse_final(line: str | None) -> Answer:
    """converged, value and uncertainty from a FINAL line (run_agents.final_line). A % after the
    uncertainty makes it a percentage of the value, and its sign is dropped."""
    if line is None:
        return Answer(None, None, None, None, ("no FINAL line",))
    notes: list[str] = []
    word = _field(line, "converged")
    found = None if word is None else _WORD.match(word.lower())
    converged = None if found is None else found.group(1)
    if converged is None:
        notes.append("no converged=" if word is None else f"converged is not yes or no: {word!r}")
    value, _ = _read(line, "value", notes)
    uncertainty, percent = _read(line, "uncertainty", notes)
    if uncertainty is not None and percent:
        if value is None:
            notes.append("uncertainty in % of no value")
            uncertainty = None
        else:
            uncertainty = abs(value) * uncertainty / 100
    if uncertainty is not None:
        uncertainty = abs(uncertainty)
    return Answer(line, converged, value, uncertainty, tuple(notes))


# --- scoring --------------------------------------------------------------------------------


def score(label: Label, answer: Answer) -> dict[str, Any]:
    """One answer against its bundle's label."""
    verdict = {"yes": "trustworthy", "no": "not_trustworthy"}.get(answer.converged or "")
    value, u = answer.value, answer.uncertainty
    band = None if value is None or u is None else [value - u, value + u]
    holds_exact = None
    if label.exact is not None and value is not None and u is not None:
        holds_exact = abs(value - label.exact) <= u
    in_label_band = None
    if label.value is not None and label.uncertainty is not None and value is not None:
        in_label_band = abs(value - label.value) <= label.uncertainty
    u_ratio = None
    if label.uncertainty is not None and u is not None:
        u_ratio = u / label.uncertainty
    return {
        "verdict": verdict,
        "correct": verdict == label.verdict,
        "false_trust": verdict == "trustworthy" and label.verdict == "not_trustworthy",
        "missed_trust": verdict == "not_trustworthy" and label.verdict == "trustworthy",
        "value": value,
        "uncertainty": u,
        "band": band,
        "band_holds_exact": holds_exact,
        "in_label_band": in_label_band,
        "u_ratio": u_ratio,
    }


def check_protocol(
    record: dict[str, Any], init: dict[str, Any] | None, *, clean: bool, where: str
) -> None:
    """Refuse a run that broke the protocol: the transcript's start must show the condition's
    tools and servers, the working folder and the model; the copy must be unchanged; and a
    scored run must come from committed code."""
    if init is None:
        raise ScoreError(f"{where}: the transcript has no start (init event)")
    if init.get("cwd") != STUDY:
        raise ScoreError(f"{where}: working folder {init.get('cwd')!r}, not {STUDY}")
    if init.get("model") != record["model"]:
        raise ScoreError(f"{where}: model {init.get('model')!r}, not {record['model']!r}")
    listed: list[Any] = init.get("tools") or []
    tools = {str(tool) for tool in listed}
    base = set(TOOLS.split(","))
    started: list[dict[str, Any]] = init.get("mcp_servers") or []
    servers = [(s.get("name"), s.get("status")) for s in started]
    if record["condition"] == "A":
        if tools != base or servers:
            raise ScoreError(f"{where}: condition A with tools {sorted(tools)}, servers {servers}")
    else:
        extra = tools - base
        if (
            not base <= tools
            or not extra
            or any(not tool.startswith(f"mcp__{SERVER}__") for tool in extra)
            or servers != [(SERVER, "connected")]
        ):
            raise ScoreError(f"{where}: condition B with tools {sorted(tools)}, servers {servers}")
    if record.get("unchanged") is not True:
        raise ScoreError(f"{where}: the bundle copy changed during the run")
    if clean and str(record.get("foam_verify", "")).endswith("-dirty"):
        raise ScoreError(f"{where}: a scored run from uncommitted code")


def score_runs(out: Path, labels: dict[str, Label], *, clean: bool) -> list[dict[str, Any]]:
    """One row per record in out/runs.jsonl, in its order: scored, or set aside."""
    index = out / "runs.jsonl"
    if not index.is_file():
        raise ScoreError(f"no runs.jsonl in {out}")
    rows: list[dict[str, Any]] = []
    slots: set[tuple[str, str, str, int]] = set()
    servers: dict[str, Any] = {}  # by model: the local server its first run recorded, or None
    for number, text in enumerate(index.read_text(encoding="utf-8").splitlines(), start=1):
        if not text.strip():
            continue
        record: dict[str, Any] = json.loads(text)
        where = f"runs.jsonl line {number} ({record.get('transcript')})"
        label = labels.get(str(record.get("bundle")))
        if label is None:
            raise ScoreError(f"{where}: no label for bundle {record.get('bundle')!r}")
        if record.get("condition") not in CONDITIONS:
            raise ScoreError(f"{where}: unknown condition {record.get('condition')!r}")
        transcript = out / str(record["transcript"])
        if not transcript.is_file():
            raise ScoreError(f"{where}: transcript missing")
        row: dict[str, Any] = {
            "model": record["model"],
            "condition": record["condition"],
            "bundle": label.id,
            "run": record["run"],
            "transcript": record["transcript"],
            "label": label.verdict,
        }
        reason = set_aside_reason(record)
        if record.get("set_aside") is not None or reason is not None:
            if record.get("set_aside") != reason:
                raise ScoreError(
                    f"{where}: marked set aside as {record.get('set_aside')!r}, but by the rule "
                    f"it is {reason!r}"
                )
            rows.append({**row, "status": "set_aside", "reason": reason})
            continue
        summary = summarise(transcript)
        check_protocol(record, summary.init, clean=clean, where=where)
        slot = (str(record["model"]), str(record["condition"]), label.id, int(record["run"]))
        if slot in slots:
            raise ScoreError(f"{where}: a second run that counts for {slot}")
        slots.add(slot)
        server = record.get("server")
        if servers.setdefault(str(record["model"]), server) != server:
            raise ScoreError(
                f"{where}: {record['model']} ran on a server other than its first run's: "
                f"{server}, not {servers[str(record['model'])]}"
            )
        line = final_line(summary.answer)
        if line != record.get("final"):
            raise ScoreError(f"{where}: the index's FINAL line is not the transcript's")
        answer = parse_final(line)
        rows.append(
            {
                **row,
                "status": "timed_out" if record["timed_out"] else "finished",
                "final": line,
                "converged": answer.converged,
                "notes": list(answer.notes),
                **score(label, answer),
                "duration_s": record.get("duration_s"),
                "num_turns": record.get("num_turns"),
                # API prices are Claude's; a local model has none.
                "total_cost_usd": None if server else record.get("total_cost_usd"),
                "permission_denials": record.get("permission_denials"),
                "foam_verify": record.get("foam_verify"),
            }
        )
    return rows


# --- the tables -----------------------------------------------------------------------------


def percent(k: int, n: int) -> str:
    """k of n, with the percentage rounded half up; - for none."""
    return "-" if n == 0 else f"{k} of {n} ({(200 * k + n) // (2 * n)}%)"


def fraction(k: int, n: int) -> str:
    return "-" if n == 0 else f"{k} of {n}"


def _g(x: float) -> str:
    return f"{x:.6g}"


def groups(rows: Sequence[dict[str, Any]]) -> list[tuple[str, str]]:
    return sorted({(str(r["model"]), str(r["condition"])) for r in rows})


def counts(rows: Sequence[dict[str, Any]], model: str, condition: str) -> dict[str, Any]:
    """The counts for one model and condition."""
    mine = [r for r in rows if r["model"] == model and r["condition"] == condition]
    counted = [r for r in mine if r["status"] != "set_aside"]
    broken = [r for r in counted if r["label"] == "not_trustworthy"]
    sound = [r for r in counted if r["label"] == "trustworthy"]
    bands = [r for r in counted if r["band_holds_exact"] is not None]
    return {
        "model": model,
        "condition": condition,
        "runs": len(counted),
        "set_aside": len(mine) - len(counted),
        "correct": sum(bool(r["correct"]) for r in counted),
        "false_trust": sum(bool(r["false_trust"]) for r in broken),
        "broken_runs": len(broken),
        "missed_trust": sum(bool(r["missed_trust"]) for r in sound),
        "sound_runs": len(sound),
        "no_verdict": sum(r["verdict"] is None for r in counted),
        "timed_out": sum(r["status"] == "timed_out" for r in counted),
        "bands_holding_exact": sum(bool(r["band_holds_exact"]) for r in bands),
        "bands_stated": len(bands),
    }


def _answer_word(row: dict[str, Any]) -> str:
    return {"trustworthy": "yes", "not_trustworthy": "no"}.get(str(row["verdict"]), "-")


def _stated(row: dict[str, Any], label: Label) -> str:
    value, u = row["value"], row["uncertainty"]
    if value is None:
        return "none"
    text = _g(value) + ("" if u is None else f" ± {_g(u)}")
    marks: list[str] = []
    if row["band_holds_exact"] is not None:
        marks.append("holds exact" if row["band_holds_exact"] else "misses exact")
    if label.verdict == "trustworthy" and row["in_label_band"] is not None:
        marks.append("in label's band" if row["in_label_band"] else "outside label's band")
    return text + (f" ({', '.join(marks)})" if marks else "")


def markdown(rows: Sequence[dict[str, Any]], labels: dict[str, Label], source: str) -> str:
    counted = [r for r in rows if r["status"] != "set_aside"]
    keys = groups(rows)
    commits: dict[str, int] = {}
    for r in counted:
        commits[str(r["foam_verify"])] = commits.get(str(r["foam_verify"]), 0) + 1
    out = [
        "# Scores",
        "",
        f"Scored by `eval/score.py` from `runs.jsonl` and the transcripts beside it, against "
        f"{source}, by the rules in `eval/README.md` (Scoring). {len(counted)} runs count and "
        f"{len(rows) - len(counted)} were set aside. The runs are from foam-verify at "
        + ", ".join(
            f"`{c[:7]}{'-dirty' if c.endswith('-dirty') else ''}` ({n})"
            for c, n in sorted(commits.items())
        )
        + ".",
        "",
        "| Model | Condition | Runs | Verdict right | False trust | Sound bundles rejected | "
        "No verdict | Bands holding the exact value |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for model, condition in keys:
        s = counts(rows, model, condition)
        out.append(
            f"| {model} | {condition} | {s['runs']} | {percent(s['correct'], s['runs'])} | "
            f"{percent(s['false_trust'], s['broken_runs'])} | "
            f"{percent(s['missed_trust'], s['sound_runs'])} | {s['no_verdict']} | "
            f"{fraction(s['bands_holding_exact'], s['bands_stated'])} |"
        )
    out += [
        "",
        "False trust: converged=yes on a bundle labelled not trustworthy. Sound bundles rejected: "
        "converged=no on one labelled trustworthy. No verdict: no FINAL line, or converged neither "
        "yes nor no; never right. Bands: of the answers that state a value and an uncertainty on "
        "a bundle with an exact value, how many bands hold it.",
        "",
        "## By bundle",
        "",
        "Each run's verdict in run order: yes or no from its FINAL line, - for no verdict, and how "
        "many are right.",
        "",
        "| Bundle | Label | Reasons | " + " | ".join(f"{m} {c}" for m, c in keys) + " |",
        "|---|---|---|" + "---|" * len(keys),
    ]
    for label in sorted(labels.values(), key=lambda lb: lb.id):
        cells: list[str] = []
        for model, condition in keys:
            mine = sorted(
                (
                    r
                    for r in counted
                    if r["bundle"] == label.id
                    and r["model"] == model
                    and r["condition"] == condition
                ),
                key=lambda r: int(r["run"]),
            )
            right = sum(bool(r["correct"]) for r in mine)
            cells.append(
                " ".join(_answer_word(r) for r in mine) + f" ({right} of {len(mine)})"
                if mine
                else ""
            )
        verdict = label.verdict.replace("_", " ")
        reasons = ", ".join(label.reasons) or "-"
        out.append(f"| {label.id} | {verdict} | {reasons} | " + " | ".join(cells) + " |")
    stated = [
        lb
        for lb in sorted(labels.values(), key=lambda lb: lb.id)
        if lb.exact is not None or lb.verdict == "trustworthy"
    ]
    if stated:
        out += [
            "",
            "## Stated values",
            "",
            "Each answer's value and uncertainty, by run. Where the bundle has an exact value, "
            "whether the band holds it; on a sound bundle, whether the value lies in the label's "
            "band (foam-verify's value and U on the committed study).",
            "",
            "| Bundle | Label's value | Run | " + " | ".join(f"{m} {c}" for m, c in keys) + " |",
            "|---|---|---|" + "---|" * len(keys),
        ]
        for label in stated:
            reference: list[str] = []
            if label.value is not None and label.uncertainty is not None:
                reference.append(f"{_g(label.value)} ± {_g(label.uncertainty)}")
            if label.exact is not None:
                reference.append(f"exact {_g(label.exact)}")
            runs = sorted({int(r["run"]) for r in counted if r["bundle"] == label.id})
            for k in runs:
                cells: list[str] = []
                for model, condition in keys:
                    match = [
                        r
                        for r in counted
                        if r["bundle"] == label.id
                        and r["model"] == model
                        and r["condition"] == condition
                        and int(r["run"]) == k
                    ]
                    cells.append(_stated(match[0], label) if match else "")
                out.append(
                    f"| {label.id} | {'; '.join(reference)} | {k} | " + " | ".join(cells) + " |"
                )
    out += [
        "",
        "## Time and usage",
        "",
        "| Model | Condition | Runs | Median time | Median turns | Cost at API prices | "
        "Refused tool calls | Timed out |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for model, condition in keys:
        mine = [r for r in counted if r["model"] == model and r["condition"] == condition]
        times = [float(r["duration_s"]) for r in mine if r["duration_s"] is not None]
        turns = [int(r["num_turns"]) for r in mine if r["num_turns"] is not None]
        costs = [float(r["total_cost_usd"]) for r in mine if r["total_cost_usd"] is not None]
        cost = f"${sum(costs):.2f}" if costs else "-"
        refused = sum(int(r["permission_denials"] or 0) for r in mine)
        timed_out = sum(r["status"] == "timed_out" for r in mine)
        median_time = f"{statistics.median(times):.0f} s" if times else "-"
        median_turns = f"{statistics.median(turns):g}" if turns else "-"
        out.append(
            f"| {model} | {condition} | {len(mine)} | {median_time} | {median_turns} | "
            f"{cost} | {refused} | {timed_out} |"
        )
    aside = [r for r in rows if r["status"] == "set_aside"]
    if aside:
        out += [
            "",
            "## Set aside",
            "",
            "Runs that did not finish for a reason outside the agent's answer; each slot ran "
            "again.",
            "",
            "| Model | Condition | Bundle | Run | Reason | Transcript |",
            "|---|---|---|---|---|---|",
        ]
        for r in aside:
            out.append(
                f"| {r['model']} | {r['condition']} | {r['bundle']} | {r['run']} | {r['reason']} | "
                f"`{r['transcript']}` |"
            )
    return "\n".join(out) + "\n"


def write(out: Path, rows: Sequence[dict[str, Any]], labels: dict[str, Label], source: str) -> str:
    (out / "scores.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    text = markdown(rows, labels, source)
    (out / "scores.md").write_text(text, encoding="utf-8")
    return text


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--pilot", action="store_true", help="the pilot runs, with its labels")
    parser.add_argument("--runs", type=Path, help="the folder with runs.jsonl")
    args = parser.parse_args(argv)
    try:
        if args.pilot:
            labels = load_labels(PILOT_LABELS)
            source = "`eval/pilot/labels.toml` (written after the pilot ran, to try the scorer)"
            out: Path = args.runs or HERE / "pilot" / "runs"
        else:
            labels = load_labels(LABELS, LABELS_SHA256)
            source = (
                f"`eval/labels.toml` (sha256 `{LABELS_SHA256[:12]}`, the labels committed at "
                f"`{LABELS_COMMIT[:7]}`)"
            )
            out = args.runs or HERE / "runs"
        rows = score_runs(out, labels, clean=not args.pilot)
    except ScoreError as error:
        print(f"score.py: {error}", file=sys.stderr)
        return 2
    text = write(out, rows, labels, source)
    print(text.split("\n## ")[0].rstrip())
    print(f"\nscores: {out / 'scores.jsonl'}, {out / 'scores.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
