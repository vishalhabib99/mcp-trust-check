"""Unit tests for the release decision: pure function over the three tools' --json report shapes."""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from decision import BLOCK, FIX_FIRST, SHIP, decide  # noqa: E402


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
    base = {"connect_error": None, "sanity_percent": 100.0, "grade": "A", "tools": list(tools)}
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
    for flag in ({"empty_content": True}, {"schema_violation": True}, {"echo_mismatch_inputs": ["q"]}):
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
    assert report.startswith("## mcp-trust-check — BLOCK")
