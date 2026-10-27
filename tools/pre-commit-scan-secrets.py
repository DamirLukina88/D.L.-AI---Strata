#!/usr/bin/env python3
"""Git pre-commit hook: block a commit whose staged files contain a credential, or whose added lines carry this
machine's private details (the home directory, the folder the checkout sits in, the user's email from
~/.config/dl-ai/profile.json).  The details are read here at run time, so this file names none of them.

Install:  ln -sf ../../tools/pre-commit-scan-secrets.py .git/hooks/pre-commit
Bypass a false positive once with:  git commit --no-verify
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dl_auditing import scan_secrets_in_text  # noqa: E402

staged = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
                        capture_output=True, check=True).stdout.decode().split("\0")
failed = False
for name in filter(None, staged):
    blob = subprocess.run(["git", "show", f":{name}"], capture_output=True).stdout
    if b"\0" in blob[:8192]:
        continue  # binary
    text = blob.decode("utf-8", "replace")
    if "scan-secrets: fake-fixtures" in text[:2000]:
        continue  # a test file whose fake keys exercise the scanner itself
    ok, msg = scan_secrets_in_text(text, name)
    if not ok:
        failed = True
        print(f"[pre-commit] {name}\n{msg}\n", file=sys.stderr)
if failed:
    print("[pre-commit] commit blocked: move the value to ~/.config/dl-ai/secrets.env", file=sys.stderr)
    sys.exit(1)


def private_strings() -> list[str]:
    root = Path(__file__).resolve().parents[1]           # the checkout (the hook is a link to this file)
    out = [str(Path.home()), str(root.parent)]
    try:
        out.append(str(json.loads((Path.home() / ".config" / "dl-ai" / "profile.json").read_text()).get("email") or ""))
    except (OSError, ValueError, AttributeError):
        pass
    return [x for x in out if len(x) > 4 and x != "/home"]


private = private_strings()
added = subprocess.run(["git", "diff", "--cached", "-U0", "--diff-filter=ACMR", "--", ".", ":!bench/results"],
                       capture_output=True).stdout.decode("utf-8", "replace")
hits, current = [], ""
for line in added.splitlines():
    if line.startswith("+++ b/"):
        current = line[6:]
    elif line.startswith("+") and not line.startswith("+++"):
        found = [x for x in private if x.lower() in line.lower()]
        if found:
            hits.append(f"  {current}: {line[1:].strip()[:120]}")
if hits:
    print("[pre-commit] commit blocked: added lines carry this machine's paths or the user's email "
          "(use Path.home(), a path relative to the checkout, or the profile):\n" + "\n".join(hits[:20])
          + (f"\n  ... and {len(hits) - 20} more" if len(hits) > 20 else ""), file=sys.stderr)
    sys.exit(1)
