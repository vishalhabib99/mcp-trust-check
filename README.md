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
| `include-destructive` | `false` | Also let mcp-fuzz test tools without `readOnlyHint: true`. Only turn this on against a server you're confident is safe to call blindly — see mcp-fuzz's README Safety section before using it. |
| `fail-under` | `0` | Fail the workflow if the combined score is below this percent. `0` disables gating. |
| `comment` | `true` | Post the combined report as a PR comment. |

## Outputs

`doctor-score` / `doctor-grade`, `fuzz-score` / `fuzz-grade`, `reality-score` / `reality-grade` (empty if neither `run` nor `url` was set), and `combined-score` / `combined-grade`.

## What the combined score means — and doesn't

The combined score is a plain, unweighted average of whichever of the three scores actually ran (one or three — never two, since fuzz and reality-check both run when `run` or `url` is set, or neither does). No tool is weighted more heavily than another; that would require a judgment call about which failure mode matters more that this project isn't going to make for you. Treat it as a single skim-friendly number for a PR check, not a substitute for reading the three sections underneath it — each retains its own real caveats (mcp-fuzz's crash-resilience score, for instance, deliberately doesn't grade whether a *successful* call's output was actually correct; that's what the reality-check section is for).

This repo contains no new detection logic of its own — it's orchestration over the three published tools, each independently dogfooded against 40+ real-world MCP servers (see each tool's own README for that history). If a check here is wrong, the bug is almost certainly in the underlying tool, not in the combining step.

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

**One real call per `call_tool`, not three** — the reason this exists as its own composed wrapper rather than "just call all three gates yourself": `mcp_fuzz.gate.LatencyGate.timed_call` and `mcp_reality_check.gate.guarded_call` each make their own real call to the tool. Calling both back to back would mean two real invocations per logical call — wasteful for an idempotent tool, actively wrong for a non-idempotent or destructive one. `GuardedSession` calls the tool exactly once and fans the single real response out to each sibling package's own pure, already-tested per-response functions instead — verified directly: a real test wraps the underlying session's `call_tool` with a call counter and asserts it fires exactly once per `GuardedSession.call_tool`.

Same scope discipline as its three parts: correctness and latency, not security — see each sibling's own README for why that's a deliberate boundary, not an oversight. Dogfooded live against the official `@modelcontextprotocol/server-memory` reference server — registration, a real `create_entities` call, and a real `read_graph` call, all clean.

## License

MIT
