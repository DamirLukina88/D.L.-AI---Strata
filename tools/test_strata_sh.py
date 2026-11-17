"""strata.sh against stub systemctl / curl / pgrep (no server, no systemd):
- with the systemd unit active, stop and restart go through systemctl (a kill was undone 5 s later by Restart=always,
  and restart's nohup copy then raced systemd's for the port);
- a stale pid file naming some other process is not trusted (stop killed whatever reused the number).

Run: python tools/test_strata_sh.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STUB_SYSTEMCTL = """#!/bin/sh
echo "systemctl $*" >> "$LOG"
case "$*" in
  *" cat "*) [ -f "$STATE/unit" ] && exit 0 || exit 1 ;;
  *is-active*) [ -f "$STATE/active" ] && exit 0 || exit 3 ;;
  *" stop "*) rm -f "$STATE/active" ;;
  *" start "*|*" restart "*) touch "$STATE/active" ;;
esac
exit 0
"""
STUB_CURL = '#!/bin/sh\necho "curl $*" >> "$LOG"\n[ -f "$STATE/active" ] && echo \'{"status": "ok"}\'\nexit 0\n'
STUB_PGREP = '#!/bin/sh\nexit 1\n'


class StrataSh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.dir, self.bin, self.state = d / "strata", d / "bin", d / "state"
        for p in (self.dir, self.bin, self.state):
            p.mkdir()
        shutil.copy(ROOT / "strata.sh", self.dir / "strata.sh")
        for name, body in (("systemctl", STUB_SYSTEMCTL), ("curl", STUB_CURL), ("pgrep", STUB_PGREP)):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.log = d / "calls.log"
        self.log.touch()

    def run_sh(self, *args):
        env = {**os.environ, "PATH": f"{self.bin}:/usr/bin:/bin", "LOG": str(self.log), "STATE": str(self.state),
               "START_TIMEOUT": "10"}
        env.pop("RUN_SCRIPT", None)
        r = subprocess.run(["sh", str(self.dir / "strata.sh"), *args], capture_output=True, text=True, env=env,
                           timeout=60)
        return r.returncode, r.stdout + r.stderr, self.log.read_text()

    def test_stop_and_restart_go_through_the_unit(self):
        (self.state / "unit").touch()
        (self.state / "active").touch()
        rc, out, calls = self.run_sh("restart")
        self.assertEqual(rc, 0, out)
        self.assertIn("--user restart strata-server.service", calls)
        rc, out, calls = self.run_sh("stop")
        self.assertEqual(rc, 0, out)
        self.assertIn("--user stop strata-server.service", calls)
        self.assertFalse((self.state / "active").exists())

    def test_start_uses_the_unit_when_there_is_one(self):
        (self.state / "unit").touch()
        rc, out, calls = self.run_sh("start")
        self.assertEqual(rc, 0, out)
        self.assertIn("--user start strata-server.service", calls)
        self.assertIn("ready", out)

    def test_a_stale_pid_file_is_not_killed(self):
        other = subprocess.Popen(["sleep", "30"])
        self.addCleanup(other.kill)
        (self.dir / "strata-server.pid").write_text(str(other.pid))
        rc, out, _ = self.run_sh("stop")
        self.assertIn("not running", out)
        time.sleep(0.3)
        self.assertIsNone(other.poll(), "stop killed a process that is not Strata")
        self.assertFalse((self.dir / "strata-server.pid").exists())


if __name__ == "__main__":
    unittest.main()
