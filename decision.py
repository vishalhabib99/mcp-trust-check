"""Turns the three tools' JSON reports into one release decision: SHIP, FIX-FIRST, or BLOCK.

The combined score is an average, and an average can hide the one failure that matters:
a server that crashes on a single bad input can still average 95%. The decision works the
other way round. It runs a short list of explicit rules over the raw findings, and the
worst finding wins. Every rule that fires is listed as a reason, so the verdict is never
a black box.

Same discipline as the rest of the trilogy: no LLM, no weights, deterministic. Stdlib only,
because combine.py runs it straight from the Action checkout.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SHIP = "SHIP"
FIX_FIRST = "FIX-FIRST"
BLOCK = "BLOCK"


@dataclass
class Decision:
    verdict: str
    blockers: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _doctor_issues(doctor: dict) -> list[dict]:
    issues = list(doctor.get("repo_issues", []))
    for tool in doctor.get("tools", []):
        issues.extend(tool.get("issues", []))
    return issues


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def decide(doctor: dict | None, fuzz: dict | None, reality: dict | None) -> Decision:
    blockers: list[str] = []
    fixes: list[str] = []
    notes: list[str] = []

    if doctor is not None:
        issues = _doctor_issues(doctor)
        sec_errors = [i for i in issues if i.get("category") == "security" and i.get("severity") == "error"]
        sec_warnings = [i for i in issues if i.get("category") == "security" and i.get("severity") != "error"]
        quality_errors = [i for i in issues if i.get("category") != "security" and i.get("severity") == "error"]
        if sec_errors:
            checks = sorted({i["check"] for i in sec_errors})
            blockers.append(f"mcp-doctor: {_count(len(sec_errors), 'security error')} ({', '.join(checks)})")
        if sec_warnings:
            fixes.append(f"mcp-doctor: {_count(len(sec_warnings), 'security warning')}")
        if quality_errors:
            fixes.append(f"mcp-doctor: {_count(len(quality_errors), 'spec/documentation error')}")

    if fuzz is not None:
        if fuzz.get("connect_error"):
            blockers.append(f"mcp-fuzz: server never connected ({fuzz['connect_error']})")
        if fuzz.get("crash_count", 0) > 0:
            blockers.append(f"mcp-fuzz: {_count(fuzz['crash_count'], 'crash')} on bad input (the server process died)")
        if fuzz.get("terminated_early"):
            blockers.append(f"mcp-fuzz: run ended early ({fuzz['terminated_early']})")
        if fuzz.get("timeout_count", 0) > 0:
            fixes.append(f"mcp-fuzz: {_count(fuzz['timeout_count'], 'timeout')} on bad input")
        concurrency = (fuzz.get("concurrency") or {}).get("flagged_tools") or []
        if concurrency:
            fixes.append(f"mcp-fuzz: {_count(len(concurrency), 'tool')} misbehaved under concurrent calls")
        stale = (fuzz.get("sequence") or {}).get("stale_after_delete_count", 0)
        if stale:
            fixes.append(f"mcp-fuzz: {_count(stale, 'resource')} still readable after delete")
        orphans = (fuzz.get("cross_resource") or {}).get("orphaned_child_count", 0)
        if orphans:
            fixes.append(f"mcp-fuzz: {_count(orphans, 'child resource')} left orphaned after parent delete")

    if reality is not None:
        if reality.get("connect_error"):
            blockers.append(f"mcp-reality-check: server never connected ({reality['connect_error']})")
        tools = reality.get("tools", [])
        refusals = [t["name"] for t in tools if t.get("refusal_in_disguise")]
        if refusals:
            # An agent reads a disguised refusal as success and acts on it: the worst silent failure.
            blockers.append(f"mcp-reality-check: disguised refusal from {', '.join(refusals)}")
        empty = [t["name"] for t in tools if t.get("empty_content")]
        if empty:
            fixes.append(f"mcp-reality-check: empty content from {', '.join(empty)}")
        schema = [t["name"] for t in tools if t.get("schema_violation")]
        if schema:
            fixes.append(f"mcp-reality-check: output breaks its own schema in {', '.join(schema)}")
        echo = [t["name"] for t in tools if t.get("echo_mismatch_inputs")]
        if echo:
            fixes.append(f"mcp-reality-check: output ignores its input in {', '.join(echo)}")

    if fuzz is None and reality is None:
        notes.append(
            "Runtime checks were not run, so this decision covers static analysis only. "
            "A SHIP here means the source looks clean, not that the server behaves."
        )

    verdict = BLOCK if blockers else FIX_FIRST if fixes else SHIP
    return Decision(verdict=verdict, blockers=blockers, fixes=fixes, notes=notes)


def render_markdown(d: Decision) -> str:
    icon = {SHIP: "✅", FIX_FIRST: "🟡", BLOCK: "⛔"}[d.verdict]
    lines = [f"### Release decision: {icon} {d.verdict}"]
    if d.blockers:
        lines.append("\n**Blockers** (any one of these blocks release):")
        lines.extend(f"- {b}" for b in d.blockers)
    if d.fixes:
        lines.append("\n**Fix first** (shippable once addressed, or knowingly accepted):")
        lines.extend(f"- {f}" for f in d.fixes)
    if not d.blockers and not d.fixes:
        lines.append("\nNo rule fired.")
    for n in d.notes:
        lines.append(f"\n> {n}")
    return "\n".join(lines) + "\n"
