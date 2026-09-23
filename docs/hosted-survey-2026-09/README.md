# How 10 hosted MCP servers describe their tools

Snapshot taken 2026-09-22. Covers 10 public MCP servers that answer over Streamable HTTP without auth: 32 tools and 110 parameters in total.

**Method:** only what every MCP client already does on connect, which is `initialize` + `tools/list`. **No tool was called.** Reproduce with `pip install 'mcp==2.1.1' && python survey.py results.json` (Python 3.11+). Raw data: [`results.json`](results.json). Token counts are chars ÷ 4, a rough estimate rather than a tokenizer count.

I first planned to fuzz these servers with mcp-fuzz and mcp-reality-check, which send malformed and wrong-type inputs. I dropped that plan. Doing it would mean hitting other companies' production endpoints (one of them an LLM-backed tool that costs its owner money per call) without asking. Runtime testing belongs on servers you run yourself.

| Server | Tools | Annotated | readOnly | Model-facing tokens (per tool) | Sent over the wire | Protocol |
|---|---|---|---|---|---|---|
| DeepWiki | 3 | **0/3** | **0/3** | 264 (88) | 383 | 2025-11-25 |
| GitMCP | 5 | **0/5** | **0/5** | 718 (143) | 718 | 2025-03-26 |
| Cloudflare Docs | 2 | 2/2 | 2/2 | 250 (125) | 447 | 2025-11-25 |
| Context7 | 2 | 2/2 | 2/2 | 1,148 (574) | 1,216 | 2025-11-25 |
| Hugging Face | 4 | 4/4 | 4/4 | 1,850 (462) | 4,703 | 2025-11-25 |
| Microsoft Learn | 3 | 3/3 | 3/3 | 950 (316) | 1,213 | 2025-06-18 |
| Exa | 2 | 2/2 | 2/2 | 522 (261) | 593 | 2025-11-25 |
| AWS Knowledge | 5 | 5/5 | 5/5 | 1,873 (374) | 1,976 | 2025-03-26 |
| Svelte | 4 | 4/4 | 4/4 | 1,251 (312) | **6,154** | 2025-06-18 |
| Kiwi.com | 2 | 2/2 | 1/2 | 3,199 (**1,599**) | 4,526 | 2025-11-25 |

"Model-facing" means name + description + inputSchema, which is what most clients put in the model's context. "Sent over the wire" is the full `tools/list` entry.

## Findings

**1. 2 of 10 servers ship no annotations, so 8 tools that only read look destructive to clients.**
DeepWiki (`read_wiki_structure`, `read_wiki_contents`, `ask_wiki_question`) and GitMCP (fetch/search docs and code) don't set `annotations`. The MCP spec defaults are `readOnlyHint: false` and `destructiveHint: true`, so a client that follows the spec must treat `read_wiki_contents` as a tool that may destroy something. A cautious agent host has to ask before each call, and safety tooling (including mine, on default settings) skips these tools. GitMCP's case is a bug, not a choice. Its source added `readOnlyHint: true` to every tool in March ([#210](https://github.com/idosal/git-mcp/pull/210)), but `src/index.ts` passes the annotations after the callback, and the TypeScript SDK silently ignores them there. Reported with the cause and a likely fix in [idosal/git-mcp#266](https://github.com/idosal/git-mcp/issues/266). A server's source code can say one thing while what it serves says another, which is one reason to check the live `tools/list` rather than only the code. The other 8 servers annotate all 24 of their tools. Kiwi.com gets this exactly right: `search-flight` is read-only, and `feedback-to-devs`, which sends a message to their team, is not.

**2. The context cost per tool varies about 18x: 88 tokens to about 1,600.**
DeepWiki's average tool costs about 88 model-facing tokens. Kiwi.com's `search-flight` alone costs about 3,200, because it has 47 parameters and every one of them is described. That's a reasonable trade-off (a rich schema instead of guessing), not sloppiness. Still, one tool from one server takes more context than all three of DeepWiki's plus all five of GitMCP's together.

**3. What goes over the wire isn't what the model sees.**
Svelte sends about 6,150 tokens of tool definitions, but only about 1,250 reach the model. The rest is the same ~4 KB icon repeated on each of the 4 tools, plus `title` fields that copy the full description in 3 of 4 tools (the spec intends `title` as a short display name). Hugging Face sends about 2.5x its model-facing size, mostly as `outputSchema`. This costs latency and bandwidth on every connect, not context. It's a gap that tools auditing only the model-facing schema don't catch.

**4. Descriptions are mostly in good shape.**
107 of 110 parameters have descriptions. The one real gap is Cloudflare Docs' `query`, a bare `{"type": "string"}`, although the tool's 535-character description covers it. Output schemas are rarer: 12 of 32 tools.

**5. The servers span three protocol revisions.**
6 servers negotiated 2025-11-25, 2 negotiated 2025-06-18, and 2 (GitMCP, AWS Knowledge) negotiated 2025-03-26.

## Not covered
- Runtime behavior (crashes, wrong-type handling, disguised refusals). That needs tool calls, which this survey deliberately didn't make.
- Servers that need auth (GitHub, Linear, Stripe, Semgrep and others). Semgrep returned an error on initialize.
- Any change after 2026-09-22. This is one snapshot.
