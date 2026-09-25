"""Unit tests for the release decision: pure function over the three tools' --json report shapes."""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from decision import BLOCK, FIX_FIRST, HIGH, LOW, MEDIUM, SHIP, decide  # noqa: E402


def _doctor(*issues, repo_issues=()):
    return {
        "percent": 95.0,
        "grade": "A",
        "tools": [{"name": "t", "issues": list(issues)}],
        "repo_issues": list(repo_issues),
    }


def _issue(check, severity, category="quality"):
    return {"tool": "t", "file": "s.py", "line": 1, "check": check, "message": "", "severity": severity, "category": category}


def _fuzz(**overrides):
    base = {
        "connect_error": None,
        "terminated_early": None,
        "tested_count": 10,
        "skipped_count": 0,
        "crash_count": 0,
        "timeout_count": 0,
        "crash_resilience_percent": 100.0,
        "grade": "A",
        "concurrency": {"flagged_tools": []},
        "sequence": {"stale_after_delete_count": 0},
        "cross_resource": {"orphaned_child_count": 0},
    }
    base.update(overrides)
    return base


def _reality(*tools, **overrides):
    base = {"connect_error": None, "checkable_count": 1, "sanity_percent": 100.0, "grade": "A", "tools": list(tools)}
    base.update(overrides)
    return base


def _tool(name, **flags):
    t = {"name": name, "refusal_in_disguise": False, "empty_content": False, "schema_violation": False, "echo_mismatch_inputs": []}
    t.update(flags)
    return t


def test_clean_full_run_ships():
    d = decide(_doctor(), _fuzz(), _reality(_tool("a")))
    assert d.verdict == SHIP
    assert d.blockers == [] and d.fixes == [] and d.notes == []


def test_one_crash_blocks_even_when_the_average_is_high():
    # The whole point: 95% doctor, 99% fuzz, 100% reality averages to an A, but a crash still blocks.
    d = decide(_doctor(), _fuzz(crash_count=1, crash_resilience_percent=99.0), _reality(_tool("a")))
    assert d.verdict == BLOCK
    assert any("1 crash " in b for b in d.blockers)


def test_disguised_refusal_blocks_and_names_the_tool():
    d = decide(_doctor(), _fuzz(), _reality(_tool("search", refusal_in_disguise=True)))
    assert d.verdict == BLOCK
    assert "search" in d.blockers[0]


def test_security_error_blocks_but_security_warning_only_needs_a_fix():
    assert decide(_doctor(_issue("shell_injection", "error", "security")), None, None).verdict == BLOCK
    assert decide(_doctor(_issue("broad_fs", "warning", "security")), None, None).verdict == FIX_FIRST


def test_quality_warning_alone_still_ships():
    assert decide(_doctor(_issue("vague_description", "warning")), _fuzz(), _reality()).verdict == SHIP


def test_repo_level_issues_count_too():
    d = decide(_doctor(repo_issues=[_issue("secret_in_repo", "error", "security")]), None, None)
    assert d.verdict == BLOCK


def test_fix_level_runtime_findings():
    cases = [
        _fuzz(timeout_count=2),
        _fuzz(concurrency={"flagged_tools": [{"name": "x"}]}),
        _fuzz(sequence={"stale_after_delete_count": 1}),
        _fuzz(cross_resource={"orphaned_child_count": 1}),
    ]
    for fuzz in cases:
        assert decide(_doctor(), fuzz, _reality()).verdict == FIX_FIRST, fuzz
    for flag in ({"empty_content": True}, {"schema_violation": True}):
        assert decide(_doctor(), _fuzz(), _reality(_tool("a", **flag))).verdict == FIX_FIRST, flag


def test_blockers_outrank_fixes_and_all_reasons_are_kept():
    d = decide(_doctor(), _fuzz(crash_count=1, timeout_count=1), _reality())
    assert d.verdict == BLOCK
    assert len(d.blockers) == 1 and len(d.fixes) == 1


def test_connect_error_blocks():
    assert decide(_doctor(), _fuzz(connect_error="boom"), _reality(connect_error="boom")).verdict == BLOCK


def test_static_only_run_says_so():
    d = decide(_doctor(), None, None)
    assert d.verdict == SHIP
    assert d.notes and "static analysis only" in d.notes[0]


def test_combine_writes_decision_to_report_and_outputs(tmp_path):
    (tmp_path / "doctor-report.json").write_text(json.dumps(_doctor()))
    (tmp_path / "fuzz-report.json").write_text(json.dumps(_fuzz(crash_count=1, crash_resilience_percent=99.0)))
    (tmp_path / "reality-report.json").write_text(json.dumps(_reality(_tool("a"))))
    out = tmp_path / "gh_output"
    subprocess.run(
        [sys.executable, str(REPO / "combine.py")],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_OUTPUT": str(out)},
        check=True,
    )
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert outputs["decision"] == BLOCK
    assert outputs["blocker-count"] == "1"
    assert outputs["combined-grade"] == "A"  # the average alone would have said ship
    report = (tmp_path / "combined-report.md").read_text()
    assert report.startswith("## mcp-trust-check — BLOCK (HIGH confidence)")
    assert outputs["confidence"] == HIGH
    assert outputs["needs-human-review"] == "true"


def test_full_coverage_ship_is_high_confidence_and_needs_no_review():
    d = decide(_doctor(), _fuzz(), _reality(_tool("a")))
    assert (d.verdict, d.confidence, d.needs_human_review, d.coverage_percent) == (SHIP, HIGH, False, 100.0)


def test_coverage_thresholds():
    # The real case that motivated this: chrome-devtools-mcp, 8 of 30 tools called, still a SHIP.
    assert decide(_doctor(), _fuzz(tested_count=8, skipped_count=22), _reality()).confidence == LOW
    assert decide(_doctor(), _fuzz(tested_count=5, skipped_count=5), _reality()).confidence == MEDIUM
    assert decide(_doctor(), _fuzz(tested_count=8, skipped_count=2), _reality()).confidence == HIGH


def test_low_confidence_ship_still_needs_review():
    d = decide(_doctor(), _fuzz(tested_count=3, skipped_count=6), _reality())
    assert d.verdict == SHIP and d.confidence == LOW and d.needs_human_review
    assert any("3 of 9 tools" in r for r in d.confidence_reasons)
    assert any("include-destructive" in r for r in d.confidence_reasons)


def test_static_only_is_low_confidence():
    d = decide(_doctor(), None, None)
    assert d.confidence == LOW and d.needs_human_review and d.coverage_percent is None


def test_no_checkable_response_caps_at_medium():
    assert decide(_doctor(), _fuzz(), _reality(checkable_count=0)).confidence == MEDIUM


def test_block_is_high_confidence_regardless_of_coverage():
    d = decide(_doctor(), _fuzz(crash_count=1, tested_count=1, skipped_count=29), _reality())
    assert d.verdict == BLOCK and d.confidence == HIGH and d.needs_human_review


def test_fix_first_always_needs_review():
    d = decide(_doctor(), _fuzz(timeout_count=1), _reality())
    assert d.verdict == FIX_FIRST and d.confidence == HIGH and d.needs_human_review


def test_echo_mismatch_is_a_note_not_a_rule():
    # Matches mcp-reality-check, which reports echo mismatch separately and never scores it.
    # Real case: server-everything's get-structured-content and chrome-devtools-mcp both hit it.
    d = decide(_doctor(), _fuzz(), _reality(_tool("a", echo_mismatch_inputs=["New York"])))
    assert d.verdict == SHIP and d.fixes == []
    assert any("not scored" in n for n in d.notes)


def test_slow_and_large_responses_are_notes_not_rules():
    fuzz = _fuzz(
        latency={"slow_tools": [{"name": "get_console_message", "duration_ms": 436.2, "reasons": []}]},
        response_size={"bloated_tools": [{"name": "list_processes", "response_chars": 104000, "reasons": []}]},
    )
    d = decide(_doctor(), fuzz, _reality())
    assert d.verdict == SHIP and d.fixes == []
    assert any("get_console_message (436ms)" in n for n in d.notes)
    assert any("list_processes (104,000 chars)" in n for n in d.notes)
