#!/usr/bin/env bash
# tools/run_tests.sh - every test suite of this fork, run the way each needs, with one summary at the end.
# No GPU, no model and no running server needed (the engine's own C++ tests are ctest, see docs/AMD_HIP.md).
#
#   tools/run_tests.sh            server, tools and web app tests
#   tools/run_tests.sh --android  the same plus the Android app's unit tests and lint (needs the Android SDK)
#
# The tools tests run one module at a time from the repo root (python -m unittest tools.test_x) with tools/ on the
# import path: some import `tools.<module>` (only from the root), others `import dl_cli` (only with tools/ on the path),
# and `unittest discover` can't import tools/ at all (it has no __init__.py).
set -u
cd "$(dirname "$0")/.." || exit 1
PY=${PYTHON:-.venv/bin/python}
[ -x "$PY" ] || PY=python3
LOG=$(mktemp -d)
declare -a SUMMARY
fail=0

run() {                                       # run <name> <command...>: one line in the summary, output in $LOG
  local name=$1; shift
  if "$@" >"$LOG/$name.log" 2>&1; then
    SUMMARY+=("ok    $name")
  else
    SUMMARY+=("FAIL  $name   (see $LOG/$name.log)")
    fail=1
  fi
}

echo "Server tests (serve/) ..."
run serve "$PY" -m unittest discover -s serve -p 'test_*.py' -t .

echo "Tools tests (tools/, one module at a time) ..."
tools_failed=()
for f in tools/test_*.py; do
  mod=tools.$(basename "$f" .py)
  PYTHONPATH="tools${PYTHONPATH:+:$PYTHONPATH}" "$PY" -m unittest "$mod" >"$LOG/$mod.log" 2>&1 || tools_failed+=("$mod")
done
if [ ${#tools_failed[@]} -eq 0 ]; then
  SUMMARY+=("ok    tools ($(ls tools/test_*.py | wc -l) modules)")
else
  SUMMARY+=("FAIL  tools: ${tools_failed[*]}   (logs in $LOG)")
  fail=1
fi

echo "Web app tests (Node) ..."
for f in tools/test_*.js; do
  run "$(basename "$f" .js)" node "$f"
done

if [ "${1:-}" = "--android" ]; then
  echo "Android unit tests and lint ..."
  run android bash -c "cd android && ./gradlew -q testDebugUnitTest lintDebug"
fi

echo
printf '%s\n' "${SUMMARY[@]}"
exit $fail
