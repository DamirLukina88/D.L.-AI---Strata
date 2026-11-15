"""Tool definitions the model is offered (DL_TOOLS, DL_PLAN_TOOLS) and the per-request tool list.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
try:
    from .dl_common import dl_mcp
except ImportError:
    from dl_common import dl_mcp


# Official D.L. AI Tool Definitions
DL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "PROPOSE and execute a bash command in the workspace directory. Operating System: linux.",
            "parameters": {
                "type": "object",
                "properties": {
                    "CommandLine": {
                        "type": "string",
                        "description": "The exact shell command line string to execute."
                    },
                    "Cwd": {
                        "type": "string",
                        "description": "Working directory for the command (defaults to workspace)."
                    },
                    "toolSummary": {
                        "type": "string",
                        "description": "Brief 2-5 word noun phrase describing the specific task."
                    }
                },
                "required": ["CommandLine"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "switch_workspace",
            "description": "Switch the active project working directory to the specified path. All relative paths, bash commands, and the local wiki will resolve in the new directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Target absolute or relative directory path to switch to (e.g. '~/DL-AI-workspace', '~/projects/myapp')."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_file",
            "description": "View the contents of a file from the local filesystem with optional line slicing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "AbsolutePath": {
                        "type": "string",
                        "description": "Path to file to view (absolute or relative to workspace)."
                    },
                    "StartLine": {
                        "type": "integer",
                        "description": "Optional start line number, 1-indexed inclusive."
                    },
                    "EndLine": {
                        "type": "integer",
                        "description": "Optional end line number, 1-indexed inclusive."
                    }
                },
                "required": ["AbsolutePath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_to_file",
            "description": "Create a new file or completely overwrite an existing file with given code content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "TargetFile": {
                        "type": "string",
                        "description": "The target file to create and write code to."
                    },
                    "CodeContent": {
                        "type": "string",
                        "description": "The exact code contents to write to the file."
                    },
                    "Overwrite": {
                        "type": "boolean",
                        "description": "Set to true to overwrite an existing file."
                    }
                },
                "required": ["TargetFile", "CodeContent", "Overwrite"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_file_content",
            "description": "Edit an existing file by replacing a single contiguous block of target text with replacement text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "TargetFile": {
                        "type": "string",
                        "description": "The target file to modify."
                    },
                    "TargetContent": {
                        "type": "string",
                        "description": "The exact substring to be replaced."
                    },
                    "ReplacementContent": {
                        "type": "string",
                        "description": "The complete replacement content."
                    }
                },
                "required": ["TargetFile", "TargetContent", "ReplacementContent"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "exa_web_search",
            "description": "Search the live web using Exa AI semantic search. Returns top webpage titles, URLs, and clean text summaries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query string."
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (1-10, default 5)."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_library_id",
            "description": "Resolves a package or product name to a Context7-compatible library ID (e.g. '/websites/deepwiki_fastapi_fastapi', '/vercel/next.js'). Call before get_library_docs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "libraryName": {
                        "type": "string",
                        "description": "Library or framework name (e.g. 'fastapi', 'react', 'next.js', 'tailwindcss', 'pytorch')."
                    }
                },
                "required": ["libraryName"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_library_docs",
            "description": "Fetches up-to-date official documentation and code examples for a library using Context7.",
            "parameters": {
                "type": "object",
                "properties": {
                    "context7CompatibleLibraryID": {
                        "type": "string",
                        "description": "Exact Context7 library ID from resolve_library_id (e.g. '/websites/deepwiki_fastapi_fastapi')."
                    },
                    "topic": {
                        "type": "string",
                        "description": "Topic or concept to focus on (e.g. 'routes', 'middleware', 'hooks', 'authentication')."
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["code", "info"],
                        "description": "Documentation mode: 'code' for API references and code examples (default), 'info' for conceptual guides."
                    }
                },
                "required": ["context7CompatibleLibraryID"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memory",
            "description": "Long-term memory shared with Claude Code and Antigravity: global rules (household, PC, every project) plus this project's decisions, constraints and preferences. Search before guessing; read pages by path; save what is worth keeping. Use it for work on a project or the house, not for a greeting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "read", "write", "remember", "digest", "history", "diff", "undo", "lint", "projects", "env_list", "backup"]
                    },
                    "query": {"type": "string", "description": "Search terms (search)."},
                    "path": {"type": "string", "description": "Page path, e.g. 'global/preferences/ac.md' or 'projects/strata/decisions/x.md' (read)."},
                    "scope": {"type": "string", "enum": ["auto", "global", "project", "all"], "description": "search: auto = global + this project. write/remember: 'project' (default) or 'global' (every agent, every project; asks the user)."},
                    "page_type": {"type": "string", "enum": ["decision", "concept", "entity", "preference", "artifact", "log"]},
                    "slug": {"type": "string", "description": "kebab-case file name without .md (write)."},
                    "title": {"type": "string"},
                    "description": {"type": "string", "description": "One line under 150 characters."},
                    "content": {"type": "string", "description": "Markdown body (write) or the fact (remember)."},
                    "tags": {"type": "string", "description": "Comma-separated tags."},
                    "rev": {"type": "string", "description": "jj revision for diff/undo (default '@-')."},
                    "limit": {"type": "integer", "description": "Max results (default 8)."}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_chat",
            "description": "Save the current conversation as a Markdown file in the active workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Optional custom filename to save the markdown chat to (e.g. 'notes.md' or 'plan.md'). Defaults to timestamped name."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_health",
            "description": "Get real-time system hardware health metrics: CPU, RAM, VRAM, Swap, GPU usage, and server stats. Use it when the user asks about the machine's load, memory or GPU, or a task needs those numbers; a greeting or a question about yourself does not.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_engine_status",
            "description": "Get the Strata AI engine status: loaded model, context size, props, slots, and engine health. Use it when the user asks about the engine or the model's settings, or a task needs them; a greeting or a question about yourself does not.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_conversation",
            "description": "Reset the current conversation history and clear short-term context memory immediately.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


# Core 6 Engineering Suite for Local LLM High Velocity:
# 1. run_command, 2. switch_workspace, 3. view_file, 4. write_to_file, 5. replace_file_content, 6. memory
# (Auditing, testing, and health are active via slash commands /health, /diff, /test, /secrets, /syntax)
DL_ACT_TOOLS = DL_TOOLS


def find_wiki_script(workspace: Path) -> Path | None:
    candidates = [
        workspace / "wiki" / "scripts" / "wiki.py",
        Path.home() / "Desktop" / "local-wiki" / "scripts" / "wiki.py",
        Path.home() / ".gemini" / "config" / "plugins" / "local-wiki-plugin" / "skills" / "local-wiki" / "scripts" / "wiki.py",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def resolve_wiki_root(workspace: Path) -> Path | None:
    # A wiki is only active if it exists directly within the defined project folder
    local_wiki = (workspace / "wiki").resolve()
    if local_wiki.is_dir():
        return local_wiki
    return None


def get_active_tools(workspace: Path, mode: str = "act", registry=None) -> list[dict]:
    base_tools = DL_PLAN_TOOLS if mode == "plan" else DL_ACT_TOOLS
    if registry is not None and registry.active:
        # the small `mcp` switch, plus the tools of the MCP servers that are on right now; built-ins the catalogue
        # loads on demand (Exa, Context7) leave the always-on list
        taken = registry.replaced()
        base_tools = [t for t in base_tools if t["function"]["name"] not in taken]
        base_tools = [*base_tools, registry.meta_tool(), *registry.tools(mode)]
    return base_tools


def web_docs_tools_hint() -> str:
    """The web search and docs tools, as the system prompt names them."""
    if dl_mcp is not None and dl_mcp.CATALOG_PATH.is_file():
        servers, _, _ = dl_mcp.load_catalog()
        taken = {r for e in servers.values() for r in e.replaces}
        if {"exa_web_search", "resolve_library_id", "get_library_docs"} <= taken:
            return "the `exa` (web search) and `context7` (library docs) servers, turned on with `mcp` when needed"
    return "`exa_web_search`, `resolve_library_id`, `get_library_docs`"


# Read-only exploration and architecture toolset for Plan Mode (strictly excludes write_to_file and replace_file_content)
DL_PLAN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "PROPOSE and execute an inspection or read-only bash command (e.g. ls, cat, find, grep). File writes or destructive changes are prohibited in Plan Mode. Operating System: linux.",
            "parameters": {
                "type": "object",
                "properties": {
                    "CommandLine": {
                        "type": "string",
                        "description": "The exact shell command line string to execute."
                    },
                    "Cwd": {
                        "type": "string",
                        "description": "Working directory for the command (defaults to workspace)."
                    },
                    "toolSummary": {
                        "type": "string",
                        "description": "Brief 2-5 word noun phrase describing the specific task."
                    }
                },
                "required": ["CommandLine"]
            }
        }
    },
    next(t for t in DL_TOOLS if t["function"]["name"] == "switch_workspace"),
    next(t for t in DL_TOOLS if t["function"]["name"] == "view_file"),
    next(t for t in DL_TOOLS if t["function"]["name"] == "memory"),
    next(t for t in DL_TOOLS if t["function"]["name"] == "exa_web_search"),
    next(t for t in DL_TOOLS if t["function"]["name"] == "resolve_library_id"),
    next(t for t in DL_TOOLS if t["function"]["name"] == "get_library_docs"),
    next(t for t in DL_TOOLS if t["function"]["name"] == "save_chat"),
    next(t for t in DL_TOOLS if t["function"]["name"] == "get_system_health"),
    next(t for t in DL_TOOLS if t["function"]["name"] == "get_engine_status"),
    next(t for t in DL_TOOLS if t["function"]["name"] == "clear_conversation"),
]
