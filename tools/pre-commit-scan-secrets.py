#!/usr/bin/env python3
"""Git pre-commit hook: block a commit whose staged files contain a credential.

Install:  ln -sf ../../tools/pre-commit-scan-secrets.py .git/hooks/pre-commit
Bypass a false positive once with:  git commit --no-verify
"""
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
    ok, msg = scan_secrets_in_text(blob.decode("utf-8", "replace"), name)
    if not ok:
        failed = True
        print(f"[pre-commit] {name}\n{msg}\n", file=sys.stderr)
if failed:
    print("[pre-commit] commit blocked: move the value to ~/.config/dl-ai/secrets.env", file=sys.stderr)
    sys.exit(1)
