"""Combines the doctor/fuzz/reality-check JSON+text reports into one score, one release decision, and one markdown summary.

Run by action.yml as a step, not meant to be used standalone. Reads whichever
*-report.json / *-report.txt files are present in the working directory (doctor
always runs; fuzz/reality only if `run` or `url` was set) and writes combined-report.md
plus the combine step's GITHUB_OUTPUT entries.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from decision import decide, render_markdown


def grade_for_percent(pct: float) -> str:
    if pct >= 90:
        return "A"
    if pct >= 80:
        return "B"
    if pct >= 70:
        return "C"
    if pct >= 60:
        return "D"
    return "F"


def read_json(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def read_text(path: str) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    return p.read_text()


def main() -> None:
    scores: dict[str, float] = {}
    grades: dict[str, str] = {}
    sections: list[str] = []

    doctor = read_json("doctor-report.json")
    if doctor is not None:
        scores["doctor"] = doctor["percent"]
        grades["doctor"] = doctor["grade"]
        text = read_text("doctor-report.txt") or ""
        sections.append(f"### mcp-doctor (static) — {doctor['percent']}% ({doctor['grade']})\n```\n{text}\n```")

    fuzz = read_json("fuzz-report.json")
    if fuzz is not None:
        scores["fuzz"] = fuzz["crash_resilience_percent"]
        grades["fuzz"] = fuzz["grade"]
        text = read_text("fuzz-report.txt") or ""
        sections.append(
            f"### mcp-fuzz (runtime crash resilience) — {fuzz['crash_resilience_percent']}% ({fuzz['grade']})\n```\n{text}\n```"
        )

    reality = read_json("reality-report.json")
    if reality is not None:
        scores["reality"] = reality["sanity_percent"]
        grades["reality"] = reality["grade"]
        text = read_text("reality-report.txt") or ""
        sections.append(
            f"### mcp-reality-check (runtime output fidelity) — {reality['sanity_percent']}% ({reality['grade']})\n```\n{text}\n```"
        )

    if not scores:
        raise SystemExit("combine.py: no reports found — doctor step should always produce one, something is wrong")

    combined = sum(scores.values()) / len(scores)
    combined_grade = grade_for_percent(combined)

    skipped_note = ""
    if "fuzz" not in scores or "reality" not in scores:
        skipped_note = (
            "\n> mcp-fuzz and mcp-reality-check were skipped — no `run` or `url` input was given, so only "
            "the static mcp-doctor check ran. Pass `run: \"<command that launches the server>\"` (stdio) "
            "or `url: \"https://.../mcp\"` (Streamable HTTP) to also run the runtime checks.\n"
        )

    decision = decide(doctor, fuzz, reality)

    summary = (
        f"## mcp-trust-check — {decision.verdict} ({decision.confidence} confidence) · combined score: {combined:.0f}% ({combined_grade})\n"
        f"{skipped_note}\n" + render_markdown(decision) + "\n" + "\n\n".join(sections) + "\n"
    )
    Path("combined-report.md").write_text(summary)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"doctor-score={scores.get('doctor', '')}\n")
            f.write(f"doctor-grade={grades.get('doctor', '')}\n")
            f.write(f"fuzz-score={scores.get('fuzz', '')}\n")
            f.write(f"fuzz-grade={grades.get('fuzz', '')}\n")
            f.write(f"reality-score={scores.get('reality', '')}\n")
            f.write(f"reality-grade={grades.get('reality', '')}\n")
            f.write(f"combined-score={combined:.2f}\n")
            f.write(f"combined-grade={combined_grade}\n")
            f.write(f"decision={decision.verdict}\n")
            f.write(f"blocker-count={len(decision.blockers)}\n")
            f.write(f"fix-count={len(decision.fixes)}\n")
            f.write(f"confidence={decision.confidence}\n")
            f.write(f"needs-human-review={'true' if decision.needs_human_review else 'false'}\n")
            cov = decision.coverage_percent
            f.write(f"coverage-percent={'' if cov is None else cov}\n")


if __name__ == "__main__":
    main()
