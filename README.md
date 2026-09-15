# mcp-trust-check

One GitHub Action that runs the full MCP trust & safety trilogy — [`mcp-doctor`](https://github.com/vishalhabib99/mcp-doctor), [`mcp-fuzz`](https://github.com/vishalhabib99/mcp-fuzz), [`mcp-reality-check`](https://github.com/vishalhabib99/mcp-reality-check) — against an [MCP](https://modelcontextprotocol.io) server and posts one combined score, instead of three separate installs and three separate reports.

Each of the three tools already works standalone and does something the other two structurally can't:

- **mcp-doctor** reads the server's source and checks spec conformance/security/documentation — no server execution needed.
- **mcp-fuzz** actually launches the server and calls every tool with schema-derived inputs, checking crash resilience, latency, response size, and (opt-in) concurrency and resource-lifecycle correctness.
- **mcp-reality-check** also launches the server, but checks whether a tool's *successful* response is actually trustworthy — no disguised refusals, no empty content, no output that quietly ignores its own schema.

None of them use an LLM judge anywhere — every check here is deterministic and reproducible, same as the tools it wraps.

## Use

Static-only — zero extra config, works on any checked-out repo:

```yaml
- uses: actions/checkout@v4
- uses: vishalhabib99/mcp-trust-check@main
  with:
    path: .
```

Full trilogy — also add `run` with the command that actually starts your server over stdio:

```yaml
- uses: actions/checkout@v4
- uses: vishalhabib99/mcp-trust-check@main
  with:
    path: .
    run: "python server.py"
    # or: run: "npx -y some-mcp-server"
    fail-under: 80
```

If `run` is left empty, only the mcp-doctor static check runs — the runtime checks are skipped and the report says so explicitly, not silently dropped. This is a real tradeoff, not a default to route around: mcp-doctor can statically analyze any checked-out repo path with no configuration, but mcp-fuzz and mcp-reality-check have to actually launch your server, and there's no way to derive a correct launch command from a repo checkout in general — you have to supply it.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `path` | `.` | Path to statically audit with mcp-doctor. |
| `run` | `""` | Command that launches the server over stdio, for the mcp-fuzz/mcp-reality-check runtime checks. Empty = runtime checks skipped. |
| `env` | `""` | Space-separated `KEY=VALUE` pairs passed through to the launched server (many real servers need an API key to start at all). |
| `include-destructive` | `false` | Also let mcp-fuzz test tools without `readOnlyHint: true`. Only turn this on against a server you're confident is safe to call blindly — see mcp-fuzz's README Safety section before using it. |
| `fail-under` | `0` | Fail the workflow if the combined score is below this percent. `0` disables gating. |
| `comment` | `true` | Post the combined report as a PR comment. |

## Outputs

`doctor-score` / `doctor-grade`, `fuzz-score` / `fuzz-grade`, `reality-score` / `reality-grade` (empty if `run` wasn't set), and `combined-score` / `combined-grade`.

## What the combined score means — and doesn't

The combined score is a plain, unweighted average of whichever of the three scores actually ran (one or three — never two, since fuzz and reality-check both need `run` or neither runs). No tool is weighted more heavily than another; that would require a judgment call about which failure mode matters more that this project isn't going to make for you. Treat it as a single skim-friendly number for a PR check, not a substitute for reading the three sections underneath it — each retains its own real caveats (mcp-fuzz's crash-resilience score, for instance, deliberately doesn't grade whether a *successful* call's output was actually correct; that's what the reality-check section is for).

This repo contains no new detection logic of its own — it's orchestration over the three published tools, each independently dogfooded against 40+ real-world MCP servers (see each tool's own README for that history). If a check here is wrong, the bug is almost certainly in the underlying tool, not in the combining step.

## License

MIT
