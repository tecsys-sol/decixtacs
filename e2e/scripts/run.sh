#!/usr/bin/env bash
# Full E2E run: stack-up -> API suite (pytest) -> browser suite (Playwright) -> stack-down.
# Exit status is non-zero if the stack fails to start or any suite fails.
#   E2E_KEEP_STACK=1   leave the stack running afterwards (for debugging)
#   E2E_SKIP_API=1 / E2E_SKIP_BROWSER=1   run only one suite
#   extra arguments are passed to Playwright (e.g. tests/01-auth.spec.ts --headed)
set -uo pipefail
# shellcheck source=env.sh
source "$(dirname "$0")/env.sh"

cleanup() {
  mkdir -p "$E2E_ROOT/test-results"
  [[ -d "$E2E_RUN/logs" ]] && cp -r "$E2E_RUN/logs" "$E2E_ROOT/test-results/stack-logs" 2>/dev/null
  if [[ "${E2E_KEEP_STACK:-0}" != "1" ]]; then "$E2E_ROOT/scripts/stack-down.sh"; fi
}
trap cleanup EXIT

rm -rf "$E2E_ROOT/test-results" "$E2E_ROOT/playwright-report"
"$E2E_ROOT/scripts/stack-up.sh" || { log "stack-up failed"; exit 2; }

api_rc=0 web_rc=0
if [[ "${E2E_SKIP_API:-0}" != "1" ]]; then
  log "API suite (e2e/api)"
  "$E2E_VENV/bin/pytest" -c "$E2E_ROOT/api/pytest.ini" "$E2E_ROOT/api" \
    --junitxml="$E2E_ROOT/test-results/api-junit.xml" || api_rc=$?
fi
if [[ "${E2E_SKIP_BROWSER:-0}" != "1" ]]; then
  log "browser suite (Playwright)"
  (cd "$E2E_ROOT" && npx playwright test "$@") || web_rc=$?
fi
log "API suite exit=$api_rc  browser suite exit=$web_rc"
[[ $api_rc -eq 0 && $web_rc -eq 0 ]]
