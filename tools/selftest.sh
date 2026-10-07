#!/usr/bin/env bash
# Self-test for the ESL feedback design QA tooling.
# Run:  bash tools/selftest.sh
# Asserts exit codes of both tools against the fixtures/ files (scratch output -> /tmp).
set -u

TOOLS="$(cd "$(dirname "$0")" && pwd)"
FIX="$TOOLS/fixtures"
OUT="$(mktemp -d /tmp/qa-selftest.XXXXXX)"
fail=0

run_check() {  # name expected_exit command...
  local name="$1" expected="$2"; shift 2
  "$@" >"$OUT/$name.log" 2>&1
  local rc=$?
  if [ "$rc" -eq "$expected" ]; then
    echo "OK   $name (exit $rc)"
  else
    echo "FAIL $name (exit $rc, expected $expected) -> $OUT/$name.log"
    fail=1
  fi
}

echo "== check_design.py =="
run_check linter_conforming  0 python3 "$TOOLS/check_design.py" "$FIX/conforming.html" --tokens "$FIX/tokens.mock.json"
run_check linter_broken      1 python3 "$TOOLS/check_design.py" "$FIX/broken.html"     --tokens "$FIX/tokens.mock.json"
run_check linter_no_spec     1 python3 "$TOOLS/check_design.py" "$FIX/broken.html"     --tokens "$OUT/nonexistent.json"

echo "== qa_run.py =="
run_check qa_conforming      0 python3 "$TOOLS/qa_run.py" "$FIX/conforming.html" --out "$OUT/qa" --prefix selftest
run_check qa_no_audio_fails  1 python3 "$TOOLS/qa_run.py" "$FIX/no-audio.html"  --out "$OUT/qa" --prefix selftest-noaudio
run_check qa_no_audio_flag   0 python3 "$TOOLS/qa_run.py" "$FIX/no-audio.html"  --out "$OUT/qa" --prefix selftest-noaudio --allow-no-audio

echo
if [ "$fail" -eq 0 ]; then echo "SELFTEST: all checks OK"; else echo "SELFTEST: FAILURES (logs in $OUT)"; fi
exit "$fail"
