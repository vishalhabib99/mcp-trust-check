"""Metadata-only survey of hosted MCP servers.

Only does what every MCP client does on connect: initialize + tools/list.
Never calls a tool.
"""
import asyncio, json, sys
from datetime import datetime, timezone
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

SERVERS = {
    "DeepWiki": "https://mcp.deepwiki.com/mcp",
    "GitMCP": "https://gitmcp.io/docs",
    "Cloudflare Docs": "https://docs.mcp.cloudflare.com/mcp",
    "Context7": "https://mcp.context7.com/mcp",
    "Hugging Face": "https://huggingface.co/mcp",
    "Microsoft Learn": "https://learn.microsoft.com/api/mcp",
    "Exa": "https://mcp.exa.ai/mcp",
    "AWS Knowledge": "https://knowledge-mcp.global.api.aws",
    "Svelte": "https://mcp.svelte.dev/mcp",
    "Kiwi.com": "https://mcp.kiwi.com",
}


def params_of(schema):
    props = (schema or {}).get("properties") or {}
    return props, set((schema or {}).get("required") or [])


def audit_tool(t):
    d = t.model_dump(mode="json", by_alias=True, exclude_none=True)
    ann = d.get("annotations") or {}
    props, required = params_of(d.get("inputSchema"))
    desc = (d.get("description") or "").strip()
    return {
        "name": d["name"],
        "has_annotations": bool(ann),
        "readOnlyHint": ann.get("readOnlyHint"),
        "destructiveHint": ann.get("destructiveHint"),
        "openWorldHint": ann.get("openWorldHint"),
        "title": bool(d.get("title") or ann.get("title")),
        "desc_len": len(desc),
        "params": len(props),
        "params_described": sum(1 for p in props.values() if (p or {}).get("description")),
        "params_typed": sum(1 for p in props.values() if (p or {}).get("type") or (p or {}).get("anyOf") or (p or {}).get("enum") or (p or {}).get("$ref")),
        "required": len(required),
        "output_schema": bool(d.get("outputSchema")),
        "def_chars": len(json.dumps(d, separators=(",", ":"))),
        # what most clients put in the model's context: name + description + inputSchema
        "model_chars": len(json.dumps({k: d.get(k) for k in ("name", "description", "inputSchema")}, separators=(",", ":"))),
        "icons": "icons" in d,
        "title_is_description": bool(d.get("title")) and d["title"].strip() == desc,
    }


async def survey(name, url):
    try:
        async with asyncio.timeout(30):
            async with streamable_http_client(url) as (r, w):
                async with ClientSession(r, w) as s:
                    init = await s.initialize()
                    tools = (await s.list_tools()).tools
                    return {
                        "server": name, "url": url, "ok": True,
                        "surveyed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "server_name": init.server_info.name,
                        "server_version": init.server_info.version,
                        "protocol": init.protocol_version,
                        "has_instructions": bool(init.instructions),
                        "tools": [audit_tool(t) for t in tools],
                    }
    except BaseException as e:
        inner = e.exceptions[0] if hasattr(e, "exceptions") else e
        return {"server": name, "url": url, "ok": False, "error": repr(inner)[:200]}


async def main():
    results = await asyncio.gather(*(survey(n, u) for n, u in SERVERS.items()))
    json.dump(results, open(sys.argv[1] if len(sys.argv) > 1 else "survey.json", "w"), indent=2)
    for r in results:
        if not r["ok"]:
            print(f"{r['server']:16} ERROR {r['error']}")
            continue
        ts = r["tools"]
        n = len(ts)
        p = sum(t["params"] for t in ts)
        print(f"{r['server']:16} tools={n:2} annotated={sum(t['has_annotations'] for t in ts)}/{n} "
              f"readOnly={sum(t['readOnlyHint'] is True for t in ts)}/{n} "
              f"titles={sum(t['title'] for t in ts)}/{n} "
              f"params_described={sum(t['params_described'] for t in ts)}/{p} "
              f"outSchema={sum(t['output_schema'] for t in ts)}/{n} "
              f"min_desc={min((t['desc_len'] for t in ts), default=0)} "
              f"wire≈{sum(t['def_chars'] for t in ts)//4}tok model≈{sum(t['model_chars'] for t in ts)//4}tok "
              f"instr={r['has_instructions']} proto={r['protocol']} v={r['server_version']}")

asyncio.run(main())
