#!/bin/bash
# foamy-bolt's own tests; tests/validate.sh runs this after the linters.
#   --ci    no Quickshell, no Omarchy host: node, the helper's Python tests
#           and kit/clipboard.sh's shell cases
#   --fast  skip the offscreen runtime test
set -uo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." || exit 1
ci=0 fast=0
for arg in "$@"; do
  case $arg in
    --ci) ci=1 ;;
    --fast) fast=1 ;;
    *)
      echo "suite.sh: unknown argument $arg" >&2
      exit 2
      ;;
  esac
done
status=0
run() {
  echo "== $*"
  "$@" || status=1
}
skip() { echo "SKIP $*"; }
run node tests/model-test.js
run node tests/i18n.test.cjs
run python3 -I tests/test_logitech_events.py
run python3 -I tests/test_logitech_status.py
# Prints a SKIP line and passes where Solaar isn't installed (CI).
run python3 -I tests/test_solaar_compat.py
# kit/clipboard.sh's shell cases (hostenv.clipboard_fakes) need no host;
# FOAMY_SUITE_CI=1 skips only the QML case, which runs Quickshell.
if ((ci)); then
  run env FOAMY_SUITE_CI=1 python3 -I tests/test_clipboard.py
else
  run python3 -I tests/test_clipboard.py
fi
if ((ci || fast)); then
  skip "tests/runtime.py: offscreen Quickshell on the Omarchy 4.5 shell"
else
  run python3 -I tests/runtime.py
fi
exit $status
