#!/usr/bin/env python3
"""dev_standards_mcp.py - Free MDN Web Docs, CppReference, Python/Node.js, and Game Programming Patterns MCP server."""
import sys
import json
import urllib.request
import urllib.parse
import re

PATTERNS = {
    "command": (
        "## Command Pattern (Game Programming Patterns - Robert Nystrom)\n"
        "- **Intent:** Encapsulate a request as an object, thereby letting you parameterize clients with different requests, queue or log requests, and support undoable operations.\n"
        "- **In Games:** Used for input handling (mapping keys to commands), AI actions, replay systems, and Undo/Redo architectures.\n"
        "- **Implementation Concept:**\n"
        "```cpp\n"
        "class Command {\n"
        "public:\n"
        "  virtual ~Command() {}\n"
        "  virtual void execute(GameActor& actor) = 0;\n"
        "  virtual void undo() {}\n"
        "};\n"
        "```"
    ),
    "state": (
        "## State Pattern & Hierarchical State Machines (Game Programming Patterns)\n"
        "- **Intent:** Allow an object to alter its behavior when its internal state changes. The object will appear to change its class.\n"
        "- **In Games:** Character state machines (standing, jumping, ducking, diving), boss AI phases, animation controllers.\n"
        "- **Avoids:** Massive `switch(state)` nested conditionals that produce state explosion bugs."
    ),
    "game loop": (
        "## Game Loop (Game Programming Patterns)\n"
        "- **Intent:** Decouple the progression of game time from user input and processor speed.\n"
        "- **Structure:** Process Input -> Update Game World -> Render.\n"
        "- **Modern Standard:** Fixed timestep for physics (`dt = 1/60s`) with variable render interpolation to prevent tunneling or physics non-determinism."
    ),
    "spatial partition": (
        "## Spatial Partition (Game Programming Patterns)\n"
        "- **Intent:** Efficiently locate objects by storing them in a data structure organized by their positions.\n"
        "- **Variants:** Grid, Quadtree (2D), Octree (3D), BVH (Bounding Volume Hierarchy).\n"
        "- **Performance:** Reduces collision detection from O(N²) to O(N log N) or O(N)."
    ),
    "component": (
        "## Component Pattern & ECS (Game Programming Patterns)\n"
        "- **Intent:** Allow a single entity to span multiple domains (rendering, physics, audio) without coupling each domain to every other.\n"
        "- **Variants:** Unity GameObject/Component, Flecs/EnTT Data-Oriented Entity Component Systems (cache-friendly contiguous array memory)."
    ),
    "observer": (
        "## Observer Pattern (Game Programming Patterns)\n"
        "- **Intent:** Define a one-to-many dependency between objects so that when one object changes state, all its dependents are notified automatically.\n"
        "- **In Games:** Achievements, audio triggers, UI event listening decoupled from core gameplay physics."
    )
}

def lookup_game_pattern(pattern_name: str) -> str:
    key = pattern_name.lower().strip()
    for k, v in PATTERNS.items():
        if k in key or key in k:
            return v + "\n\n**Reference:** Game Programming Patterns (gameprogrammingpatterns.com by Robert Nystrom)"
    return f"Pattern '{pattern_name}' not pre-cached. Available: {', '.join(PATTERNS.keys())}. Full text: https://gameprogrammingpatterns.com"

def lookup_mdn_spec(topic: str) -> str:
    try:
        encoded = urllib.parse.quote(topic)
        # Search MDN Web Docs via GitHub markdown content
        url = f"https://developer.mozilla.org/api/v1/search?q={encoded}&locale=en-US"
        req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        
        docs = data.get("documents", [])
        if not docs:
            return f"No MDN documentation entries found for: {topic}"
        
        lines = [f"## MDN Web Docs for '{topic}':\n"]
        for d in docs[:3]:
            title = d.get("title", "")
            summary = d.get("summary", "")
            mdn_path = d.get("mdn_url", "")
            full_url = f"https://developer.mozilla.org{mdn_path}"
            lines.append(f"### [{title}]({full_url})\n{summary}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"MDN search error: {e}"

def _reply(req, res):
    """Write one JSON-RPC reply: nothing for a notification, an empty result for ping, and isError on a tool
    result whose text is an error message ("... error: ...")."""
    if "id" not in req:
        return
    if req.get("method") == "ping":
        res = {"jsonrpc": "2.0", "id": req["id"], "result": {}}
    result = res.get("result")
    if req.get("method") == "tools/call" and isinstance(result, dict) and "isError" not in result:
        text = "".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
        head = text.lstrip().split(":", 1)
        result["isError"] = len(head) == 2 and len(head[0]) <= 45 and any(
            w in head[0].lower() for w in ("error", "failed"))
    sys.stdout.write(json.dumps(res) + "\n")
    sys.stdout.flush()


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue
        m, mid = req.get("method"), req.get("id")
        if m == "initialize":
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "dev-standards-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "game_pattern_lookup",
                    "description": "Look up game programming architecture patterns (Game Loop, Component/ECS, State Machine, Command, Spatial Partition) from Robert Nystrom's reference.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "Pattern name: command, state, game loop, spatial partition, component, observer"}
                        },
                        "required": ["pattern"]
                    }
                },
                {
                    "name": "mdn_lookup",
                    "description": "Look up official Mozilla Developer Network (MDN) documentation for JavaScript, Web APIs, CSS, and HTML.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "API or language feature, e.g. 'Fetch API', 'AbortController', 'Array.prototype.toSorted'"}
                        },
                        "required": ["query"]
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "game_pattern_lookup":
                text = lookup_game_pattern(args.get("pattern", ""))
            elif name == "mdn_lookup":
                text = lookup_mdn_spec(args.get("query", ""))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
