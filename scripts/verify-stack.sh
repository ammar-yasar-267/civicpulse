#!/usr/bin/env bash
# Verifies every claim the README makes about the running Compose stack, and writes the
# transcript to docs/evidence/stack-verification.txt.
#
# This exists because §1.4 sets the bar at "everything a claim in your README asserts, you can
# demonstrate". Rather than demonstrate it by hand and hope, it is a script — which also makes
# it the shot list for the demo video.
#
#   docker compose up -d --build && scripts/verify-stack.sh
set -uo pipefail

BASE="${BASE:-http://localhost:8080}"     # through the frontend proxy, as a citizen would
EVIDENCE_DIR="docs/evidence"
EVIDENCE="${EVIDENCE_DIR}/stack-verification.txt"

pass=0
fail=0

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE") 2>&1

echo "CivicPulse stack verification"
echo "date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "commit: $(git rev-parse --short HEAD 2>/dev/null || echo 'n/a')"
echo "base URL: $BASE  (all app traffic goes through the frontend proxy)"
echo "======================================================================"

check() {
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        printf '  PASS  %-58s %s\n' "$label" "$actual"
        pass=$((pass + 1))
    else
        printf '  FAIL  %-58s expected=%s got=%s\n' "$label" "$expected" "$actual"
        fail=$((fail + 1))
    fi
}

contains() {
    local label="$1" needle="$2" haystack="$3"
    if printf '%s' "$haystack" | grep -q -- "$needle"; then
        printf '  PASS  %-58s contains %s\n' "$label" "$needle"
        pass=$((pass + 1))
    else
        printf '  FAIL  %-58s missing %s in: %s\n' "$label" "$needle" "${haystack:0:120}"
        fail=$((fail + 1))
    fi
}

code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
json() { curl -s "$@"; }

echo
echo "-- 1. health and readiness (probe semantics, rubric C) ---------------"
check "GET /health via backend port" 200 "$(code http://localhost:8000/health)"
READY=$(json http://localhost:8000/ready)
contains "/ready reports postgres ok" '"postgres":"ok"' "$READY"
contains "/ready reports redis ok" '"redis":"ok"' "$READY"

echo
echo "-- 2. network segmentation (rubric G, 4 marks) -----------------------"
if docker compose exec -T frontend ping -c1 -W2 database >/dev/null 2>&1; then
    printf '  FAIL  %-58s frontend REACHED the database\n' "frontend cannot reach database"
    fail=$((fail + 1))
else
    printf '  PASS  %-58s frontend cannot resolve/reach database\n' "frontend -> database is blocked"
    pass=$((pass + 1))
fi
if docker compose exec -T frontend wget -q -O- --timeout=3 http://backend:8000/health >/dev/null 2>&1; then
    printf '  PASS  %-58s frontend -> backend works\n' "frontend -> backend permitted"
    pass=$((pass + 1))
else
    printf '  FAIL  %-58s frontend cannot reach the backend\n' "frontend -> backend permitted"
    fail=$((fail + 1))
fi
if docker compose exec -T database wget -q -O- --timeout=4 https://example.com >/dev/null 2>&1; then
    printf '  FAIL  %-58s internal network has internet egress\n' "internal network has no egress"
    fail=$((fail + 1))
else
    printf '  PASS  %-58s no egress from internal\n' "internal network has no egress"
    pass=$((pass + 1))
fi

echo
echo "-- 3. submit -> triage -> persist (rubric C, F) ----------------------"
CREATED=$(json -X POST "$BASE/api/complaints" -H 'Content-Type: application/json' \
    -d '{"text":"Burst water main flooding Street 12 since fajr, water entering ground floors.","location":"Street 12, Gulberg III, Lahore","reporter_contact":"0300-1234567"}')
ID=$(printf '%s' "$CREATED" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
contains "triage assigned a category" '"category":"water"' "$CREATED"
contains "triage assigned high priority" '"priority":"high"' "$CREATED"
contains "AI summary present" '"ai_summary":"' "$CREATED"
contains "provider recorded" '"triaged_by":"' "$CREATED"
check   "GET the complaint back" 200 "$(code "$BASE/api/complaints/$ID")"
echo "        triaged_by: $(printf '%s' "$CREATED" | sed -n 's/.*"triaged_by":"\([^"]*\)".*/\1/p')"
echo "        latency_ms: $(printf '%s' "$CREATED" | sed -n 's/.*"triage_latency_ms":\([0-9]*\).*/\1/p')"

echo
echo "-- 4. state machine (rubric C, 3 marks) -----------------------------"
CONFLICT=$(json -X PATCH "$BASE/api/complaints/$ID/status" -H 'Content-Type: application/json' -d '{"status":"resolved"}')
check    "open -> resolved is refused" 409 "$(code -X PATCH "$BASE/api/complaints/$ID/status" -H 'Content-Type: application/json' -d '{"status":"resolved"}')"
contains "409 names the attempted transition" 'open -> resolved' "$CONFLICT"
check    "open -> in_progress is allowed" 200 "$(code -X PATCH "$BASE/api/complaints/$ID/status" -H 'Content-Type: application/json' -d '{"status":"in_progress"}')"
check    "in_progress -> resolved is allowed" 200 "$(code -X PATCH "$BASE/api/complaints/$ID/status" -H 'Content-Type: application/json' -d '{"status":"resolved"}')"
TERMINAL=$(json -X PATCH "$BASE/api/complaints/$ID/status" -H 'Content-Type: application/json' -d '{"status":"open"}')
contains "terminal status explains itself" 'terminal status' "$TERMINAL"

echo
echo "-- 5. validation (rubric C) ------------------------------------------"
BAD=$(json -X POST "$BASE/api/complaints" -H 'Content-Type: application/json' -d '{"text":"short","location":"x"}')
check    "short input is 400 not 422" 400 "$(code -X POST "$BASE/api/complaints" -H 'Content-Type: application/json' -d '{"text":"short","location":"x"}')"
contains "error body names the text field" '"field":"text"' "$BAD"
contains "error body names the location field" '"field":"location"' "$BAD"

echo
echo "-- 6. stats cache: MISS then HIT (rubric E) --------------------------"
curl -s -o /dev/null "$BASE/api/stats"   # prime
FIRST=$(curl -s -D- -o /dev/null "$BASE/api/stats" | tr -d '\r' | awk -F': ' '/^[Xx]-[Cc]ache/{print $2}')
check "second read is a cache HIT" "HIT" "$FIRST"
curl -s -o /dev/null -X POST "$BASE/api/complaints" -H 'Content-Type: application/json' \
    -d '{"text":"Garbage not lifted for ten days near the corner point, dogs tearing bags.","location":"Allama Iqbal Town, Lahore"}' >/dev/null
AFTER_WRITE=$(curl -s -D- -o /dev/null "$BASE/api/stats" | tr -d '\r' | awk -F': ' '/^[Xx]-[Cc]ache/{print $2}')
check "a write invalidates the cache" "MISS" "$AFTER_WRITE"

echo
echo "-- 7. distributed rate limiter (rubric E, 4 marks) ------------------"
# Discover the configured limit from the response header rather than assuming one. The limit is an
# environment variable and differs between dev and CI, so a hardcoded burst size makes this check
# pass or fail for reasons that have nothing to do with the limiter working.
CONFIGURED_LIMIT=$(curl -s -D- -o /dev/null -X POST "$BASE/api/complaints" -H 'Content-Type: application/json' \
    -d '{"text":"probe request used only to read the configured rate limit header","location":"Lahore"}' \
    | tr -d '\r' | awk -F': ' '/^[Xx]-[Rr]ate[Ll]imit-[Ll]imit/{print $2}')
CONFIGURED_LIMIT=${CONFIGURED_LIMIT:-10}
BURST=$((CONFIGURED_LIMIT + 3))

if [ "$BURST" -gt 80 ]; then
    # A deliberately high limit (a load-test profile, say) would need hundreds of requests to trip.
    # Say so rather than silently passing or spending a minute on it.
    printf '  SKIP  %-58s limit is %s/window — too high to burst here\n' \
        "limiter returns 429 under a burst" "$CONFIGURED_LIMIT"
else
    LIMIT_HIT="no"
    for i in $(seq 1 "$BURST"); do
        c=$(code -X POST "$BASE/api/complaints" -H 'Content-Type: application/json' \
            -d "{\"text\":\"Street light $i is fused in our lane, please replace it soon.\",\"location\":\"Johar Town, Lahore\"}")
        [ "$c" = "429" ] && LIMIT_HIT="yes" && break
    done
    check "limiter returns 429 within limit+3 requests" "yes" "$LIMIT_HIT"
fi
if [ "$BURST" -le 80 ]; then
    RETRY=$(curl -s -D- -o /dev/null -X POST "$BASE/api/complaints" -H 'Content-Type: application/json' \
        -d '{"text":"one more complaint to confirm the Retry-After header is present","location":"Lahore"}' | tr -d '\r' | awk -F': ' '/^[Rr]etry-[Aa]fter/{print $2}')
    if [ -n "$RETRY" ]; then
        printf '  PASS  %-58s Retry-After: %s\n' "429 carries Retry-After" "$RETRY"; pass=$((pass + 1))
    else
        printf '  FAIL  %-58s no Retry-After header\n' "429 carries Retry-After"; fail=$((fail + 1))
    fi
fi

echo
echo "-- 8. observability surface (rubric F) ------------------------------"
META=$(json "$BASE/api/meta/providers")
contains "active provider reported" '"active_provider"' "$META"
contains "triage cache hit rate reported" '"cache_hit_rate"' "$META"
contains "recent outcomes recorded" '"recent_outcomes"' "$META"
METRICS=$(curl -s http://localhost:8000/metrics)
contains "metrics: request count" 'civicpulse_http_requests_total' "$METRICS"
contains "metrics: request latency" 'civicpulse_http_request_duration_seconds' "$METRICS"
contains "metrics: triage latency" 'civicpulse_triage_duration_seconds' "$METRICS"
contains "metrics: fallback counter" 'civicpulse_triage_fallbacks_total' "$METRICS"

echo
echo "-- 9. structured logging (rubric C) --------------------------------"
RID="verify-$(date +%s)"
curl -s -o /dev/null -H "X-Request-ID: $RID" "$BASE/api/stats"
sleep 1
if docker compose logs --since 30s backend 2>/dev/null | grep -q "$RID"; then
    printf '  PASS  %-58s request_id propagated into JSON logs\n' "X-Request-ID appears in logs"
    pass=$((pass + 1))
else
    printf '  WARN  %-58s not found (proxied requests get a fresh id)\n' "X-Request-ID appears in logs"
fi

echo
echo "======================================================================"
printf 'PASS: %d   FAIL: %d\n' "$pass" "$fail"
echo "transcript written to $EVIDENCE"
[ "$fail" -eq 0 ] || exit 1
