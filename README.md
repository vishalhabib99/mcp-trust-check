# mcp-trust-check

One GitHub Action that runs the full MCP trust & safety trilogy — [`mcp-doctor`](https://github.com/vishalhabib99/mcp-doctor), [`mcp-fuzz`](https://github.com/vishalhabib99/mcp-fuzz), [`mcp-reality-check`](https://github.com/vishalhabib99/mcp-reality-check) — against an [MCP](https://modelcontextprotocol.io) server and posts one combined score, instead of three separate installs and three separate reports. Also a Python package (`pip install mcp-trust-check`) doing the same job for a live agent session instead of a CI run — see [Live session wrapper](#live-session-wrapper) below.

Each of the three tools already works standalone and does something the other two structurally can't:

- **mcp-doctor** reads the server's source and checks spec conformance/security/documentation — no server execution needed.
- **mcp-fuzz** actually launches the server and calls every tool with schema-derived inputs, checking crash resilience, latency, response size, and (opt-in) concurrency and resource-lifecycle correctness.
- **mcp-reality-check** also launches the server, but checks whether a tool's *successful* response is actually trustworthy — no disguised refusals, no empty content, no output that quietly ignores its own schema.

None of them use an LLM judge anywhere — every check here is deterministic and reproducible, same as the tools it wraps.

## Demo

35 seconds, live run against the official MCP reference server — real output, no cherry-picking: 86%/B code quality, 100%/A crash resilience, 100%/A output fidelity, 95%/A combined.

<video src="docs/demo.mp4" controls width="100%"></video>

## Use

Static-only — zero extra config, works on any checked-out repo:

```yaml
- uses: actions/checkout@v4
- uses: vishalhabib99/mcp-trust-check@v1
  with:
    path: .
```

Full trilogy — also add `run` with the command that actually starts your server over stdio:

```yaml
- uses: actions/checkout@v4
- uses: vishalhabib99/mcp-trust-check@v1
  with:
    path: .
    run: "python server.py"
    # or: run: "npx -y some-mcp-server"
    fail-under: 80
```

Remote server — if your server ships over Streamable HTTP (a hosted/SaaS MCP server, or one your workflow starts in an earlier step), pass `url` instead of `run`:

```yaml
- uses: actions/checkout@v4
- uses: vishalhabib99/mcp-trust-check@v1
  with:
    path: .
    url: "https://example.com/mcp"
    headers: |
      Authorization=Bearer ${{ secrets.MCP_TOKEN }}
    fail-under: 80
```

Set `run` or `url`, not both — the Action fails fast if it gets both. If both are left empty, only the mcp-doctor static check runs — the runtime checks are skipped and the report says so explicitly, not silently dropped. This is a real tradeoff, not a default to route around: mcp-doctor can statically analyze any checked-out repo path with no configuration, but mcp-fuzz and mcp-reality-check have to actually launch (or connect to) your server, and there's no way to derive a correct launch command from a repo checkout in general — you have to supply it.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `path` | `.` | Path to statically audit with mcp-doctor. |
| `run` | `""` | Command that launches the server over stdio, for the mcp-fuzz/mcp-reality-check runtime checks. Empty = runtime checks skipped. |
| `url` | `""` | URL of an already-running server to test over Streamable HTTP instead of launching one with `run`. Set one or the other. |
| `headers` | `""` | HTTP headers for `url`, one `KEY=VALUE` per line (values may contain spaces — e.g. `Authorization=Bearer ...`). Pass tokens from secrets. |
| `env` | `""` | Space-separated `KEY=VALUE` pairs passed through to the launched server (many real servers need an API key to start at all). |
| `include-destructive` | `false` | Also let mcp-fuzz and mcp-reality-check test tools without `readOnlyHint: true`. Only turn this on against a server you're confident is safe to call blindly — see mcp-fuzz's README Safety section before using it. |
| `fail-under` | `0` | Fail the workflow if the combined score is below this percent. `0` disables gating. |
| `fail-on` | `never` | Fail the workflow on the release decision: `block` fails on BLOCK, `fix` fails on FIX-FIRST or BLOCK, `review` fails unless it's SHIP with HIGH confidence, `never` disables it. |
| `comment` | `true` | Post the combined report as a PR comment. |

## Outputs

`doctor-score` / `doctor-grade`, `fuzz-score` / `fuzz-grade`, `reality-score` / `reality-grade` (empty if neither `run` nor `url` was set), `combined-score` / `combined-grade`, and `decision` (`SHIP`, `FIX-FIRST`, or `BLOCK`) with `blocker-count` / `fix-count`, `confidence` (`HIGH`, `MEDIUM`, or `LOW`), `needs-human-review` (`true`/`false`) and `coverage-percent`.

## Release decision: SHIP, FIX-FIRST, or BLOCK

A score answers "how good is it on average?" The question a release actually asks is "can this go out?", and an average is the wrong tool for that. A server that crashes on one bad input, or tells an agent a failed call worked, can still average an A.

So next to the score, the report gives a **decision**, built from a short list of explicit rules over the raw findings. The worst finding wins, and every rule that fires is listed as a reason:

| Decision | Fires when |
|---|---|
| ⛔ **BLOCK** | mcp-doctor security **error** · the server crashed (process died) on any fuzz input · the server never connected, or the run ended early · any tool returned a **disguised refusal** (an agent reads it as success and acts on it) |
| 🟡 **FIX-FIRST** | mcp-doctor security warning or spec/documentation error · fuzz timeouts · tools that misbehave under concurrent calls · resources still readable after delete, or orphaned after a parent delete · empty content, or output that breaks its own schema |
| ✅ **SHIP** | none of the above |

Quality **warnings** from mcp-doctor (a vague description, say) lower the score but never change the decision. If the runtime checks were skipped, the report says the decision covers static analysis only. Use `fail-on: block` to gate PRs on it. Same design as everything else here: no LLM, no weights, deterministic, and the rules live in one short file ([`decision.py`](decision.py)) you can read in two minutes.

Checked against real runs, not just unit tests: the official memory reference server (runtime checks) gets **SHIP**, and the test fixture server, which has a tool that quietly refuses, gets **BLOCK** with that tool named.

### Confidence: should you act on the decision?

The decision says *what*. Confidence says *whether to act on it*, the same split TypeSafe's Jev model makes for agent decisions. Jev learns its confidence from training data. Here it's plainer: **how much of the server was actually exercised.** mcp-fuzz only calls tools annotated read-only unless you pass `include-destructive`, so a SHIP can rest on a small slice of the server.

| Confidence | When |
|---|---|
| **HIGH** | mcp-fuzz called at least 80% of the tools, and mcp-reality-check got a real response to check. Also every BLOCK: a crash seen once is a crash, and untested tools can only add to it. |
| **MEDIUM** | 50–79% of tools called, or no successful response for mcp-reality-check to check |
| **LOW** | under 50% called, or the runtime checks didn't run |

`needs-human-review` is `true` for everything except SHIP with HIGH confidence. Pair it with `fail-on: review` to auto-pass the clear cases and send the rest to a person.

It's a level with its reasons listed, never a number like 0.82. A calibrated probability would need past releases with known outcomes to fit against, and there aren't any, so a decimal here would claim a precision the rules don't have.

On five official or widely used servers, run locally with the defaults, all five came out SHIP. Confidence is what told them apart:

| Server | Tools called | Decision |
|---|---|---|
| `server-sequential-thinking` | 1 / 1 | SHIP, **HIGH** |
| `server-filesystem` | 10 / 14 | SHIP, MEDIUM |
| `server-everything` | 9 / 13 | SHIP, MEDIUM |
| `server-memory` | 3 / 9 | SHIP, **LOW** |
| `chrome-devtools-mcp` (52.6K★) | 8 / 30 | SHIP, **LOW** |

## What the combined score means — and doesn't

The combined score is a plain, unweighted average of whichever of the three scores actually ran (one or three — never two, since fuzz and reality-check both run when `run` or `url` is set, or neither does). No tool is weighted more heavily than another; that would require a judgment call about which failure mode matters more that this project isn't going to make for you. Treat it as a single skim-friendly number for a PR check, not a substitute for reading the three sections underneath it — each retains its own real caveats (mcp-fuzz's crash-resilience score, for instance, deliberately doesn't grade whether a *successful* call's output was actually correct; that's what the reality-check section is for).

The CI Action adds no detection logic of its own beyond the decision rules above, which only read the three tools' existing findings. It's orchestration over the three published tools, each independently dogfooded against 40+ real-world MCP servers (see each tool's own README for that history). If a check here is wrong, the bug is almost certainly in the underlying tool, not in the combining step. The live wrapper further down is different: its policy gate, audit log and PII detector are this repo's own code, with their own tests and accuracy measurements.

## Hosted servers: a metadata-only survey

The runtime checks are meant for servers you run yourself. For 10 public hosted MCP servers (Hugging Face, Microsoft Learn, AWS Knowledge, Cloudflare Docs, Context7, Exa, Svelte, Kiwi.com, DeepWiki, GitMCP), [`docs/hosted-survey-2026-09`](docs/hosted-survey-2026-09/) records only what every client reads on connect, with no tool calls. It covers annotations, the context cost per tool, and what gets sent vs. what the model sees. Headline: 2 of 10 servers mark no tool as read-only, so under the spec's defaults, 8 tools that only read look destructive.

## Live session wrapper

The Action above runs once, in CI. By now, each tool in the trilogy also has its own live counterpart, usable directly in an agent's own code: `mcp-doctor`'s [registration gate](https://github.com/vishalhabib99/mcp-doctor#runtime-gate--the-same-two-checks-applied-to-live-toolslist-metadata), `mcp-fuzz`'s [latency gate](https://github.com/vishalhabib99/mcp-fuzz#runtime-gate--the-same-two-checks-live-during-a-real-agent-session), `mcp-reality-check`'s [correctness gate](https://github.com/vishalhabib99/mcp-reality-check#runtime-gate--use-it-live-not-just-as-a-batch-audit). `GuardedSession` is the same idea as this Action, applied there: one wrapper around a real `ClientSession` that runs all three at their natural point, instead of three separate imports wired by hand.

```python
from mcp import ClientSession
from mcp_trust_check import GuardedSession

session: ClientSession = ...  # your own, already-connected session
gs = GuardedSession(session)

await gs.list_tools()  # runs mcp-doctor's checks once, at discovery
for name, result in gs.registration_results.items():
    if result.flagged:
        ...  # missing/vague description, or a real annotation conflict

result = await gs.call_tool("some_tool", {"arg": "value"})
if result.outcome != "ok":
    ...  # crashed or timed out
elif result.flagged:
    ...  # slow/bloated relative to this tool's own history, a disguised
         # refusal, empty content, or a schema violation
```

### A decision on every call: ACT, ESCALATE, or BLOCK

The release decision above runs once, in CI. Live, the question is narrower: *what should the agent do with this one response?* Every `call_tool` result carries its own decision, the per-call version of SHIP / FIX-FIRST / BLOCK:

```python
result = await gs.call_tool("some_tool", {"arg": "value"})
if result.decision == "BLOCK":        # crash, timeout, or a disguised refusal
    ...                               # don't build on this response
elif not result.should_act:           # ESCALATE, or an unchecked tool
    ...                               # hand it to a person
print(result.decision, result.confidence, result.reasons)
```

| Decision | When |
|---|---|
| **BLOCK** | the call crashed or timed out, or the response is a disguised refusal (an agent would read the failure as success and build on it) |
| **ESCALATE** | empty content, output that breaks its own schema, or a slow or large response for this tool |
| **ACT** | none of the above. An honest `isError` is an ACT: the tool told the truth, and the agent can handle it. |

Confidence is how much of this call could actually be checked:

- **HIGH**: the tool is registered, and there are at least 3 earlier calls to compare speed and size against.
- **MEDIUM**: the tool has fewer than 3 earlier calls (no speed/size baseline yet), or mcp-doctor flagged it at registration. That includes a [look-alike description](https://github.com/vishalhabib99/mcp-doctor/releases/tag/v1.12.0): two differently named tools described identically give an agent nothing to choose between.
- **LOW**: the tool never went through `list_tools`, so there was no schema to check its output against.

`should_act` is `True` for an ACT whose confidence is at least `act_threshold`. The default is `MEDIUM`, and like Jev, the check reports how sure it is while you decide how sure is sure enough: `GuardedSession(session, act_threshold="HIGH")` also escalates each tool's first few calls, and `"LOW"` acts on any ACT. An unknown value is an error. The default is looser than the release decision on purpose. Live, MEDIUM mostly means "one of the first few calls to this tool," and escalating every early call would make the gate useless; the correctness checks run on every call either way. The rules are one pure function, `decide_call`, with no model and no network.

Dogfooded on the official `@modelcontextprotocol/server-memory` server: a `read_graph` before `list_tools` came back ACT/LOW. After registration, `create_entities` came back ACT/MEDIUM (first call). `read_graph` stayed MEDIUM until its third earlier call, then moved to HIGH.

### Policy, audit log, and PII: guardrails for a live agent

Three things the trilogy used to leave out, rebuilt so nothing is guessed:

**Policy gate, checked before the call.** You write which tools the agent may call, with which arguments, and which calls need a person first. A denied or unapproved call is never sent (`result.called` is `False`).

```python
from mcp_trust_check import AuditLog, GuardedSession, Policy

policy = Policy.from_dict({
    "allow_tools": ["read_graph", "search_nodes", "create_entities"],  # optional allowlist
    "deny_tools": ["delete_entities"],                                 # always wins
    "require_approval": ["create_entities"],                           # needs approved=True
    "require_approval_for_destructive": True,                          # any tool not annotated readOnlyHint=true
    "arguments": {"search_nodes": {"query": {"pattern": "[A-Za-z0-9 ]{1,64}"}}},  # fullmatch; also "enum"
    "pii": ["card", "ssn", "iban"],                                    # the default; add "email", or [] to turn off
})
gs = GuardedSession(session, policy=policy, audit_log="agent-audit.jsonl")
result = await gs.call_tool("create_entities", {...})                # ESCALATE, not called
result = await gs.call_tool("create_entities", {...}, approved=True)  # a person said yes
```

Unknown keys or rule types are an error, never ignored. A misspelled `deny_tool` that silently allowed everything would be the worst way for a policy to fail. A tool that never went through `list_tools` counts as not read-only, so it needs approval instead of slipping through.

**Audit log.** Every call, including the ones the policy stopped, gets one JSON line with the decision, confidence and reasons. Each line carries the SHA-256 of the one before it, so an edited, deleted or reordered line breaks the chain at that point. That's tamper-evident, not tamper-proof: anyone who can rewrite the whole file can rebuild the chain, so anchor the last hash somewhere else if that matters. Argument values aren't logged by default, since they can hold the PII this checks for. You get the argument names and a hash instead (`AuditLog(path, log_arguments=True)` logs the values).

```
mcp-trust-check-audit verify agent-audit.jsonl    # OK: 17 records, chain intact, ...
mcp-trust-check-audit summary agent-audit.jsonl   # decisions per tool, top reasons
```

**PII in responses → ESCALATE.** Every response, including `isError` ones, is scanned. Every detector needs a structural validity check, not just a pattern match:

- **card**: a real network prefix, the right length, and a valid Luhn checksum
- **ssn**: dashed form, within the issued ranges
- **iban**: the right length for the country, and a valid mod-97 checksum
- **email**: off by default, since docs and git metadata are full of legitimate addresses

Findings are masked to the last 4 characters. Accuracy was measured on 20,513 real text files (300 MB of READMEs, lockfiles, JSON and source). The first version produced 195 card hits, from digit runs inside sha256 hashes and SVG path coordinates. After tightening, there were 13 hits, and every one is a genuinely card-, SSN- or IBAN-formatted value: published test cards, test IBANs in a banking server's fixtures, and an example SSN. That's 0 false positives on that corpus.

Dogfooded on the official `server-filesystem` (reading 16 real files, and a `write_file` attempt held for approval without being called) and `server-memory` (a stored test card and SSN, escalated on `create_entities` and again on `read_graph`, masked in the audit log). That run also exposed a false positive upstream: reading a README that merely mentions refusal phrases was flagged as a disguised refusal. It's fixed at the source in [mcp-reality-check 0.4.1](https://github.com/vishalhabib99/mcp-reality-check/releases/tag/v0.4.1): over 12,445 real files, flagged files went from 38 to 0, and all 12 refusal samples are still caught.

**One real call per `call_tool`, not three** — the reason this exists as its own composed wrapper rather than "just call all three gates yourself": `mcp_fuzz.gate.LatencyGate.timed_call` and `mcp_reality_check.gate.guarded_call` each make their own real call to the tool. Calling both back to back would mean two real invocations per logical call — wasteful for an idempotent tool, actively wrong for a non-idempotent or destructive one. `GuardedSession` calls the tool exactly once and fans the single real response out to each sibling package's own pure, already-tested per-response functions instead — verified directly: a real test wraps the underlying session's `call_tool` with a call counter and asserts it fires exactly once per `GuardedSession.call_tool`.

What it doesn't do: detect prompt injection or scan arguments for secrets in transit. That's the runtime-security-proxy space, which already has mature tools (see mcp-reality-check's README). What it does enforce on the security side is the operator's own policy, described above, and PII in responses. Dogfooded live against the official `@modelcontextprotocol/server-memory` reference server — registration, a real `create_entities` call, and a real `read_graph` call, all clean.

## License

MIT
