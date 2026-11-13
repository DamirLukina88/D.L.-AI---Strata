#!/usr/bin/env python3
"""tools/migrate_wikis_to_jj.py - import per-project wiki/ folders into the shared memory store (tools/dl_memory.py).

    migrate_wikis_to_jj.py --source "<project>/wiki[=slug]" ... [--global slug:rel ...] [--global-source slug]
                           [--handoffs "<folder>=slug"] [--archive <dir>]          # prints the plan, changes nothing
    ... --apply                                                                  # imports, commits, archives

Each source wiki's pages go to projects/<slug>/<type folder>/ (a flat wiki is sorted by each page's `type`), except
the pages named with --global (or every page of a --global-source), which go to global/.  index.md, changelog.md
and README.md are skipped (the store indexes itself).  Relative links are rewritten for the new places; a link to a
skipped file keeps its text only; a link to a file outside the wiki becomes an absolute path.  --apply refuses when
any page holds a credential, copies each wiki's private/.env into the store's (keys already there are kept), builds
the index, commits once in jj, then moves each source wiki/ (and --handoffs folders) under --archive, and replaces the
`<!-- local-wiki:start/end -->` block in the project's AGENTS.md / CLAUDE.md with a pointer to the store.
Paths come from the command line only, so this file names no folder of any machine.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_memory as M  # noqa: E402

SKIP_NAMES = {"index.md", "changelog.md", "README.md"}
SKIP_DIRS = {"private", "scripts", "handoffs", ".obsidian", ".git"}
BLOCK_RE = re.compile(r"<!-- local-wiki:start -->.*?<!-- local-wiki:end -->", re.S)


def parse_source(raw: str) -> tuple[Path, str]:
    path, _, slug = raw.partition("=")
    p = Path(path).expanduser().resolve()
    return p, (slug.strip() or M.slugify(p.parent.name))


def page_type(path: Path) -> str:
    meta, _, _ = M.parse_frontmatter(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return str(meta.get("type") or "concept")


def plan_pages(sources: list[tuple[Path, str]], global_rels: set[str], global_sources: set[str]):
    """[(src_path, dst_rel, slug)] for every page, and the skipped files."""
    pages, skipped = [], []
    for wiki, slug in sources:
        for p in sorted(wiki.rglob("*.md")):
            rel = p.relative_to(wiki)
            if rel.parts[0] in SKIP_DIRS or p.name in SKIP_NAMES:
                skipped.append(p)
                continue
            if len(rel.parts) == 1:                                  # a flat wiki: sort by the page's type
                ptype = page_type(p)
                if ptype not in M.FOLDERS:
                    skipped.append(p)
                    continue
                sub = Path(M.FOLDERS[ptype]) / rel.name
            else:
                sub = rel
            is_global = slug in global_sources or f"{slug}:{rel.as_posix()}" in global_rels
            dst = (Path("global") / sub) if is_global else (Path("projects") / slug / sub)
            pages.append((p, dst.as_posix(), slug))
    return pages, skipped


def rewrite_links(text: str, src: Path, dst_rel: str, root: Path, moved: dict[Path, str]) -> tuple[str, int]:
    """Links in text, rewritten for the page's new place.  Returns (text, links left pointing nowhere)."""
    dst_dir = (root / dst_rel).parent
    broken = 0

    def fix_target(target: str) -> str | None:
        nonlocal broken
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
            return target
        path_part, hash_, frag = target.partition("#")
        resolved = (src.parent / unquote(path_part)).resolve()
        if resolved in moved:
            new = os.path.relpath(root / moved[resolved], dst_dir)
            return new + (hash_ + frag if hash_ else "")
        if resolved.name in SKIP_NAMES or resolved.suffix == ".md" and not resolved.exists():
            if not resolved.exists() or resolved.name in SKIP_NAMES:
                broken += resolved.name not in SKIP_NAMES
                return None
        if resolved.exists():
            return str(resolved) + (hash_ + frag if hash_ else "")
        broken += 1
        return target

    def sub(m: re.Match) -> str:
        whole, label = m.group(0), m.group(1)
        target = m.group(2) or m.group(3)
        new = fix_target(target)
        if new is None:
            return label
        if new == target:
            return whole
        return f"[{label}](<{new}>)" if " " in new else f"[{label}]({new})"

    link = re.compile(r"(?<!!)\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^)\s]+))(?:\s+\"[^\"]*\")?\s*\)")
    out, in_fence = [], False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        out.append(line if in_fence else link.sub(sub, line))
    text = "".join(out)

    def fix_sup(m: re.Match) -> str:
        new = fix_target(m.group(2).strip().strip('"'))
        return f"{m.group(1)}{new}" if new else m.group(0)
    text = re.sub(r"(?m)^(superseded_by:\s*)(.+)$", fix_sup, text)
    return text, broken


def merge_env(src_env: Path, dst_env: Path) -> list[str]:
    """Add the keys of src_env that dst_env lacks; returns the key names added (values never printed)."""
    have = {}
    if dst_env.is_file():
        have = {m.group(1) for ln in dst_env.read_text(encoding="utf-8").splitlines() if (m := M.ENV_LINE_RE.match(ln))}
    added, lines = [], []
    for ln in src_env.read_text(encoding="utf-8").splitlines():
        m = M.ENV_LINE_RE.match(ln)
        if m and m.group(1) not in have:
            lines.append(ln)
            added.append(m.group(1))
    if lines:
        dst_env.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(dst_env.parent, 0o700)
        prefix = "" if dst_env.is_file() else M.ENV_HEADER
        with open(dst_env, "a", encoding="utf-8") as fh:
            fh.write(prefix + "\n".join(lines) + "\n")
        os.chmod(dst_env, 0o600)
    return added


def pointer_block(slug: str) -> str:
    return ("<!-- local-wiki:start -->\n## Project memory\n\n"
            f"This project's decisions, constraints and preferences live in the shared memory store as project "
            f"`{slug}` (global rules apply too), not in a `wiki/` folder. Search it before starting work "
            "(`memory_search`, or `dl_memory.py search <words>`) and save new decisions with `memory_write`.\n"
            "<!-- local-wiki:end -->")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", action="append", default=[], help="a wiki/ folder, optionally =slug")
    ap.add_argument("--global", dest="globals", action="append", default=[], help="slug:path/in/wiki.md to global/")
    ap.add_argument("--global-source", action="append", default=[], help="a slug whose every page goes to global/")
    ap.add_argument("--handoffs", action="append", default=[], help="a handoff folder =slug")
    ap.add_argument("--archive", type=Path, help="where imported folders are moved (with --apply)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--archive-only", action="store_true",
                    help="the pages are already imported (checked file by file): only archive and repoint")
    a = ap.parse_args(argv)

    root = M.resolve_memory_root()
    if root is None:
        print("Error: no memory store (RAY_MEMORY_DIR or ~/.config/dl-ai/memory.json)", file=sys.stderr)
        return 2
    sources, seen = [], set()
    for raw in a.source:
        wiki, slug = parse_source(raw)
        if not wiki.is_dir():
            print(f"Error: not a folder: {wiki}", file=sys.stderr)
            return 2
        if wiki in seen:
            continue                                    # the same wiki reached through a link
        seen.add(wiki)
        sources.append((wiki, slug))
    handoffs = [parse_source(h) for h in a.handoffs]
    pages, skipped = plan_pages(sources, set(a.globals), set(a.global_source))

    if a.archive_only:
        missing = [d for _, d, _ in pages if not (root / d).is_file()]
        if missing or not a.archive:
            print(f"Error: --archive-only needs --archive and every page imported; missing: {missing[:5]}", file=sys.stderr)
            return 1
        archive(a.archive, sources, handoffs)
        return 0
    clash = [d for d in {d for _, d, _ in pages} if (root / d).exists() or [x for _, x, _ in pages].count(d) > 1]
    leaks = [(p, err) for p, _, _ in pages if (err := M.secret_error(p.read_text(encoding="utf-8", errors="replace"), str(p)))]
    print(f"Store: {root}")
    for wiki, slug in sources:
        mine = [d for p, d, s in pages if s == slug]
        g = sum(1 for d in mine if d.startswith("global/"))
        print(f"  {slug:<30} {len(mine):>4} pages ({g} to global/)  <- {wiki}")
    for folder, slug in handoffs:
        print(f"  handoffs/{slug:<21} {len(list(folder.glob('*.md'))):>4} files       <- {folder}")
    print(f"  skipped: {len(skipped)} (index/changelog/README, private/, scripts/)")
    print("Global pages:" if any(d.startswith("global/") for _, d, _ in pages) else "Global pages: none")
    for p, d, s in pages:
        if d.startswith("global/"):
            print(f"  {d}  <- {s}:{p.name}")
    if clash:
        print("Error: these destinations already exist or repeat:\n  " + "\n  ".join(sorted(clash)), file=sys.stderr)
        return 1
    if leaks:
        print("Error: credentials found; move them to private/.env first:\n  "
              + "\n  ".join(f"{p}: {e}" for p, e in leaks), file=sys.stderr)
        return 1
    if not a.apply:
        print("\nDry run: nothing changed. Add --apply to import.")
        return 0

    moved = {p.resolve(): d for p, d, _ in pages}
    broken_total = 0
    with M.write_lock(root):
        for p, d, _ in pages:
            text, broken = rewrite_links(p.read_text(encoding="utf-8", errors="replace"), p, d, root, moved)
            broken_total += broken
            (root / d).parent.mkdir(parents=True, exist_ok=True)
            (root / d).write_text(text, encoding="utf-8")
        data = M._load_projects(root)
        for wiki, slug in sources + [(f, s) for f, s in handoffs]:
            ws = str(wiki.parent if wiki.name in ("wiki", ".dl-handoff") else wiki)
            data["by_path"][ws] = slug
            entry = data["projects"].setdefault(slug, {"name": Path(ws).name, "paths": []})
            if ws not in entry["paths"]:
                entry["paths"].append(ws)
        M._save_projects(root, data)
        for folder, slug in handoffs:
            out = root / "handoffs" / slug
            out.mkdir(parents=True, exist_ok=True)
            for f in folder.glob("*.md"):
                shutil.copy2(f, out / f.name)
        env_added = []
        for wiki, _ in sources:
            src_env = wiki / "private" / ".env"
            if src_env.is_file():
                env_added += M_env_added if (M_env_added := merge_env(src_env, root / M.ENV_REL)) else []
        dests = [d for _, d, _ in pages]
        M._approve_paths(root, [d for d in dests if d.startswith("global/")], global_ok=True)
        M._approve_paths(root, [d for d in dests if not d.startswith("global/")] + [M.PROJECTS_REL], global_ok=False)
        M.sync_index(root)
        rev = M._jj_commit(root, f"migrate: import {len(sources)} wiki(s), {len(pages)} pages", dests + [M.PROJECTS_REL])
    errors, warnings, count = M.lint_repo(root)
    print(f"\nImported {len(pages)} pages (jj {rev}); links left pointing nowhere: {broken_total}; "
          f"credential keys added to the store's vault: {len(env_added)}")
    print(f"Lint: {len(errors)} error(s), {len(warnings)} warning(s), {count} page(s)")
    for e in errors[:25]:
        print(f"  ERROR {e}")
    on_disk = sum(1 for d in dests if (root / d).is_file())
    if on_disk != len(pages):
        print(f"Error: {on_disk} of {len(pages)} pages are in the store; nothing archived.", file=sys.stderr)
        return 1

    if a.archive:
        archive(a.archive, sources, handoffs)
    return 0


def archive(where: Path, sources: list[tuple[Path, str]], handoffs: list[tuple[Path, str]]) -> None:
    if True:
        stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        base = where.expanduser() / stamp
        for wiki, slug in sources:
            target = base / slug / wiki.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(wiki), str(target))
            for name in ("AGENTS.md", "CLAUDE.md"):
                f = wiki.parent / name
                if f.is_file():
                    text = f.read_text(encoding="utf-8")
                    new = BLOCK_RE.sub(pointer_block(slug), text)
                    if new != text:
                        shutil.copy2(f, target.parent / f"{name}.before-memory")
                        f.write_text(new, encoding="utf-8")
                        print(f"  {f}: local-wiki block now points to the store")
                    if re.search(r"\bwiki/", BLOCK_RE.sub("", new)):
                        print(f"  note: {f} still mentions wiki/ outside the block")
        for folder, slug in handoffs:
            target = base / f"{slug}-handoffs" / folder.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(folder), str(target))
        print(f"Archived the imported folders under {base}")


if __name__ == "__main__":
    sys.exit(main())
