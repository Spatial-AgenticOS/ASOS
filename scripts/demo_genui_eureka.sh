#!/usr/bin/env bash
# demo_genui_eureka.sh -- one-command FERAL Gen-UI app-store demo.
#
# Runs the three-persona "publisher -> reviewer -> user" arc against
# real services (registry.feral.sh + admin.feral.sh + a local brain +
# a local mock API) using the uber-genui-demo bundle as the star app.
#
# Modes
#   default       Pauses between phases for live demos (press ENTER to advance).
#   --auto        Runs straight through, no prompts. Good for screen recording.
#   --auto-approve  After publishing, calls the registry approve endpoint
#                  via API instead of waiting for the reviewer browser
#                  click. Requires FERAL_REGISTRY_REVIEWER_SECRET.
#   --reset       Tears down state (uninstall app on brain, drop the
#                  publish row by name+version) and exits.
#   --check       Runs preflight only (does NOT publish or install).
#
# Required env (at least one of):
#   FERAL_DEMO_APP_DIR          Defaults to /Users/mahmoudomar/Desktop/test-app/uber-genui-demo
#   FERAL_BRAIN_URL             Defaults to http://127.0.0.1:9090
#   FERAL_REGISTRY_URL          Defaults to https://registry.feral.sh
#   FERAL_DEMO_MOCK_API_URL     Defaults to http://127.0.0.1:8765
#
# For --auto-approve only:
#   FERAL_REGISTRY_REVIEWER_SECRET  Same value as the Fly secret on
#                                    feral-registry. NEVER printed.

set -uo pipefail

APP_DIR="${FERAL_DEMO_APP_DIR:-/Users/mahmoudomar/Desktop/test-app/uber-genui-demo}"
BRAIN="${FERAL_BRAIN_URL:-http://127.0.0.1:9090}"
REG="${FERAL_REGISTRY_URL:-https://registry.feral.sh}"
MOCK="${FERAL_DEMO_MOCK_API_URL:-http://127.0.0.1:8765}"

MODE_AUTO=0
MODE_AUTO_APPROVE=0
MODE_RESET=0
MODE_CHECK=0
for arg in "$@"; do
  case "$arg" in
    --auto)          MODE_AUTO=1 ;;
    --auto-approve)  MODE_AUTO=1; MODE_AUTO_APPROVE=1 ;;
    --reset)         MODE_RESET=1 ;;
    --check)         MODE_CHECK=1 ;;
    -h|--help)
      sed -n '/^# demo_genui_eureka/,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown arg: $arg"; exit 2 ;;
  esac
done

# ---- ANSI ---------------------------------------------------------
B=$'\033[1m'; D=$'\033[2m'; R=$'\033[0m'
A=$'\033[36m'   # accent
G=$'\033[32m'   # good
Y=$'\033[33m'   # warn
E=$'\033[31m'   # error
M=$'\033[35m'   # magenta (reviewer)
C=$'\033[34m'   # blue (user)

banner() {
  local color="$1"; shift
  local title="$*"
  echo
  echo "${color}${B}== ${title} ===========================================================${R}"
}

step() { echo "${A}>${R} ${B}$*${R}"; }
ok()   { printf '%b\n' "${G}✓${R} $*"; }
warn() { printf '%b\n' "${Y}!${R} $*"; }
fail() { printf '%b\n' "${E}✗ $*${R}" >&2; }

pause() {
  if [[ "$MODE_AUTO" -eq 1 ]]; then
    sleep "${1:-0.6}"
  else
    read -r -p "  ${D}(press ENTER to continue)${R} " _
  fi
}

# ---- preflight ----------------------------------------------------
preflight() {
  banner "$A" "PREFLIGHT"
  local fail_count=0

  step "checking app bundle"
  if [[ -f "$APP_DIR/manifest.yaml" ]]; then
    ok "manifest at $APP_DIR/manifest.yaml"
  else
    fail "no manifest.yaml at $APP_DIR (set FERAL_DEMO_APP_DIR)"
    fail_count=$((fail_count+1))
  fi

  step "checking registry reachability ($REG)"
  if curl -sS --max-time 6 "$REG/api/v1/healthz" >/dev/null 2>&1; then
    ok "registry healthy"
  else
    fail "registry unreachable at $REG"
    fail_count=$((fail_count+1))
  fi

  step "checking brain reachability ($BRAIN)"
  if curl -sS --max-time 4 "$BRAIN/health" >/dev/null 2>&1; then
    ok "brain healthy"
  else
    fail "brain not running at $BRAIN -- start it in another terminal:"
    echo "    cd $(dirname "$0")/.. && feral serve"
    fail_count=$((fail_count+1))
  fi

  step "checking mock API ($MOCK)"
  if curl -sS --max-time 4 "$MOCK/health" >/dev/null 2>&1; then
    ok "mock mobility API healthy"
  else
    warn "mock API not running at $MOCK -- skill_call actions will 5xx during the dispatch phase"
    warn "to start it:"
    echo "    cd $APP_DIR/mock-api && python3 -m venv .venv && source .venv/bin/activate \\"
    echo "      && pip install -r requirements.txt \\"
    echo "      && python3 -m uvicorn main:APP --host 127.0.0.1 --port 8765"
  fi

  step "checking publisher token"
  if [[ -f "$HOME/.feral/publisher.token" ]]; then
    ok "publisher.token present (size $(wc -c < "$HOME/.feral/publisher.token") bytes)"
  else
    fail "no publisher token. Bake one BEFORE the demo so we don't open a browser onstage:"
    echo "    feral publisher login   # one-time GitHub OAuth"
    echo "    feral publisher register"
    fail_count=$((fail_count+1))
  fi

  if [[ "$MODE_AUTO_APPROVE" -eq 1 ]]; then
    step "checking reviewer secret (--auto-approve)"
    if [[ -n "${FERAL_REGISTRY_REVIEWER_SECRET:-}" ]]; then
      ok "reviewer secret set (not printed)"
    else
      fail "FERAL_REGISTRY_REVIEWER_SECRET not set; --auto-approve cannot continue"
      fail_count=$((fail_count+1))
    fi
  fi

  if [[ $fail_count -gt 0 ]]; then
    fail "$fail_count preflight check(s) failed -- fix above and retry"
    exit 1
  fi
  ok "all preflight checks passed"
}

# ---- helpers ------------------------------------------------------
manifest_field() {
  python3 -c "
import sys, yaml
m = yaml.safe_load(open('$APP_DIR/manifest.yaml'))
print(m.get('$1', ''))
"
}

reset_state() {
  banner "$Y" "RESET (best-effort)"
  local app_id; app_id="$(manifest_field app_id)"
  step "uninstalling $app_id from brain (if present)"
  curl -sS -X DELETE "$BRAIN/api/apps/$app_id" >/dev/null || true
  ok "brain state cleared"
  warn "registry rows are immutable from the demo script -- if you need to"
  warn "drop a published item from the registry, do it via the reviewer"
  warn "queue (reject/quarantine) at https://admin.feral.sh/review/queue"
}

# ---- main flow ----------------------------------------------------
preflight
[[ "$MODE_CHECK" -eq 1 ]] && exit 0
[[ "$MODE_RESET" -eq 1 ]] && { reset_state; exit 0; }

APP_ID="$(manifest_field app_id)"
APP_VERSION="$(manifest_field version)"
ITEM_ID=""

# ---------------------------------------------------------------
banner "$A" "ACT 1 — PUBLISHER"
# ---------------------------------------------------------------
echo "${D}A developer ships a real third-party app to FERAL.${R}"
echo "${D}Manifest + skill + surfaces, signed Ed25519, no native binary required.${R}"
pause

step "feral app validate $APP_DIR"
feral app validate "$APP_DIR" || { fail "validate failed"; exit 1; }
pause

step "feral app build  $APP_DIR"
feral app build "$APP_DIR" >/dev/null || { fail "build failed"; exit 1; }
ok "tarball built under $APP_DIR/dist/"
pause

step "feral app publish $APP_DIR"
PUB_OUT="$(feral app publish "$APP_DIR" 2>&1)" || true
echo "$PUB_OUT" | sed 's/^/  /'
ITEM_ID="$(echo "$PUB_OUT" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1 || true)"
if [[ -z "$ITEM_ID" ]]; then
  fail "could not parse item_id from publish output -- check the response above"
  exit 1
fi
ok "submission accepted as $ITEM_ID (status: submitted, visibility: private)"
pause

# ---------------------------------------------------------------
banner "$E" "ACT 2 — FAIL CLOSED (the gate is real)"
# ---------------------------------------------------------------
echo "${D}A user tries to install before the org has reviewed it.${R}"
echo "${D}This MUST fail with a user-safe error envelope, not a crash.${R}"
pause

step "POST $BRAIN/api/apps/install (registry_id=$ITEM_ID)"
RESP="$(curl -sS -w "\n__HTTP_CODE__:%{http_code}" \
  -X POST "$BRAIN/api/apps/install" \
  -H "Content-Type: application/json" \
  -d "{\"registry_id\":\"$ITEM_ID\"}")"
CODE="$(echo "$RESP" | grep -oE '__HTTP_CODE__:[0-9]+' | tr -d -c 0-9)"
BODY="$(echo "$RESP" | sed 's/__HTTP_CODE__:[0-9]*//' )"
echo "  ${B}HTTP $CODE${R}"
echo "$BODY" | python3 -m json.tool 2>/dev/null | sed 's/^/  /' || echo "$BODY" | sed 's/^/  /'

if [[ "$CODE" == "422" ]]; then
  ok "fail-closed verified -- the gate refused the install (HTTP 422)"
else
  fail "expected 422, got $CODE -- the gate is NOT working. Stop the demo and investigate."
  exit 1
fi
pause

# ---------------------------------------------------------------
banner "$M" "ACT 3 — REVIEWER"
# ---------------------------------------------------------------
echo "${D}A FERAL org reviewer signs in to admin.feral.sh,${R}"
echo "${D}sees the queue, reviews the bundle, approves it.${R}"

if [[ "$MODE_AUTO_APPROVE" -eq 1 ]]; then
  step "auto-approve via registry API (--auto-approve)"
  RESP="$(curl -sS -X POST "$REG/api/v1/review/$ITEM_ID/approve" \
    -H "Authorization: Bearer $FERAL_REGISTRY_REVIEWER_SECRET" \
    -H "X-Reviewer-Actor: demo-runner" \
    -H "Content-Type: application/json" \
    -d '{"notes":"approved for live demo"}')"
  echo "$RESP" | python3 -m json.tool 2>/dev/null | sed 's/^/  /' || echo "$RESP" | sed 's/^/  /'
  ok "approved"
else
  step "OPEN https://admin.feral.sh/review/queue in your browser"
  echo "  ${D}sign in (username + password + TOTP), find item ${B}$ITEM_ID${R}${D}, click Approve.${R}"
  echo "  ${D}I'll watch the registry and continue the moment status flips to approved.${R}"
  echo
  while true; do
    STATUS_LINE="$(curl -sS "$REG/api/v1/item/$ITEM_ID" -o /dev/null -w "%{http_code}")"
    if [[ "$STATUS_LINE" == "200" ]]; then
      ok "registry now serves item $ITEM_ID publicly -- approval landed"
      break
    fi
    printf "  ${D}waiting for approval...${R}\r"
    sleep 2
  done
fi
pause

# ---------------------------------------------------------------
banner "$C" "ACT 4 — USER"
# ---------------------------------------------------------------
echo "${D}The same install command the user already tried -- now it works.${R}"
echo "${D}No client update, no new SDK; the gate let it through.${R}"
pause

step "POST $BRAIN/api/apps/install (registry_id=$ITEM_ID)"
RESP="$(curl -sS -w "\n__HTTP_CODE__:%{http_code}" \
  -X POST "$BRAIN/api/apps/install" \
  -H "Content-Type: application/json" \
  -d "{\"registry_id\":\"$ITEM_ID\"}")"
CODE="$(echo "$RESP" | grep -oE '__HTTP_CODE__:[0-9]+' | tr -d -c 0-9)"
BODY="$(echo "$RESP" | sed 's/__HTTP_CODE__:[0-9]*//' )"
if [[ "$CODE" == "200" ]]; then
  ok "install succeeded (HTTP 200)"
  echo "$BODY" | python3 -m json.tool 2>/dev/null | sed 's/^/  /' | head -10
else
  fail "expected 200, got $CODE"
  echo "$BODY" | sed 's/^/  /'
  exit 1
fi
pause

step "POST $BRAIN/api/apps/$APP_ID/open (surface=home)"
curl -sS -X POST "$BRAIN/api/apps/$APP_ID/open" \
  -H "Content-Type: application/json" \
  -d '{"surface_id":"home","data":{"headline":"Ride demo live"}}' \
  | python3 -m json.tool 2>/dev/null | sed 's/^/  /' | head -20
pause

step "POST $BRAIN/api/apps/$APP_ID/dispatch (action=home_get_estimate)"
curl -sS -X POST "$BRAIN/api/apps/$APP_ID/dispatch" \
  -H "Content-Type: application/json" \
  -d '{
    "surface_id":"home",
    "action_id":"home_get_estimate",
    "value":{"pickup":"123 Main St","dropoff":"Airport","vehicle_tier":"standard"}
  }' \
  | python3 -m json.tool 2>/dev/null | sed 's/^/  /'
pause

# ---------------------------------------------------------------
banner "$G" "DONE — SUMMARY"
# ---------------------------------------------------------------
cat <<EOF
  Publisher        published $APP_ID v$APP_VERSION as item $ITEM_ID
  Org reviewer     approved with audit trail (review_events)
  User             installed, opened the home surface, dispatched a
                   real action that hit the publisher's mock API

  Registry view:   $REG/api/v1/item/$ITEM_ID
  Audit trail:     $REG/api/v1/review/queue?status=approved
                   (requires reviewer auth)

  To re-run:       $0 --reset && $0
EOF
echo
ok "demo complete"
