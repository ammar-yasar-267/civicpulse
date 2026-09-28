#!/usr/bin/env bash
# Zero-downtime rolling update under live load (§3.3, bonus +4).
#
#   scripts/rollout-demo.sh
#
# Drives continuous traffic through the Ingress while `kubectl set image` rolls the backend, and
# counts failures. The claim being tested is that maxUnavailable: 0 plus a preStop sleep plus
# uvicorn's graceful shutdown means ZERO failed requests during a deploy.
#
# Writes docs/evidence/zero-downtime-rollout.txt.
set -uo pipefail

NS=civicpulse
EVIDENCE=docs/evidence/zero-downtime-rollout.txt
HOST="${HOST_HEADER:-civicpulse.local}"
URL="${BASE_URL:-http://localhost}/api/stats"

mkdir -p docs/evidence
exec > >(tee "$EVIDENCE") 2>&1

echo "Zero-downtime rollout under live load"
echo "date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "commit: $(git rev-parse --short HEAD)"
echo "======================================================================"
echo
echo "Rollout strategy:"
kubectl -n "$NS" get deploy backend -o jsonpath='{.spec.strategy}' ; echo
echo "terminationGracePeriodSeconds: $(kubectl -n "$NS" get deploy backend -o jsonpath='{.spec.template.spec.terminationGracePeriodSeconds}')"
echo "preStop: $(kubectl -n "$NS" get deploy backend -o jsonpath='{.spec.template.spec.containers[0].lifecycle.preStop.exec.command}')"
echo
echo "Pods before:"
kubectl -n "$NS" get pods -l app=backend --no-headers | awk '{print "  "$1"  "$3"  age="$5}'

TOTAL=0; FAIL=0; CODES=""
STOP=/tmp/rollout-demo.stop
rm -f "$STOP"

# ---- the load generator: continuous, sequential, counts every response --------
(
    while [ ! -f "$STOP" ]; do
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H "Host: $HOST" "$URL" 2>/dev/null)
        echo "$code" >> /tmp/rollout-codes.txt
    done
) &
LOAD_PID=$!

: > /tmp/rollout-codes.txt
sleep 3

echo
echo "==> triggering the rolling update"
# A pure annotation change forces a new ReplicaSet without changing the image, so the rollout is
# exercised without needing a second image build. `kubectl rollout restart` does the same thing.
kubectl -n "$NS" rollout restart deployment/backend
kubectl -n "$NS" rollout status deployment/backend --timeout=300s

echo
echo "==> holding 10s after rollout completes"
sleep 10
touch "$STOP"
wait "$LOAD_PID" 2>/dev/null

TOTAL=$(wc -l < /tmp/rollout-codes.txt | tr -d ' ')
OK=$(grep -c '^200$' /tmp/rollout-codes.txt)
FAIL=$((TOTAL - OK))

echo
echo "Pods after:"
kubectl -n "$NS" get pods -l app=backend --no-headers | awk '{print "  "$1"  "$3"  age="$5}'
echo
echo "======================================================================"
echo "requests during the rollout : $TOTAL"
echo "HTTP 200                    : $OK"
echo "failures (non-200 or error) : $FAIL"
if [ "$FAIL" -gt 0 ]; then
    echo
    echo "non-200 responses by code:"
    grep -v '^200$' /tmp/rollout-codes.txt | sort | uniq -c | sed 's/^/  /'
fi
echo
if [ "$FAIL" -eq 0 ]; then
    echo "RESULT: ZERO failed requests across a full rolling update."
    echo
    echo "Why this works:"
    echo "  maxUnavailable: 0  — capacity is added before any is removed."
    echo "  preStop sleep 10   — the pod leaves the Service endpoints BEFORE it stops accepting"
    echo "                       connections. Endpoint removal and SIGTERM are concurrent, not"
    echo "                       ordered, so without this sleep the pod would still receive new"
    echo "                       connections while already draining, and those would be refused."
    echo "  graceful shutdown  — uvicorn finishes in-flight requests (app/main.py lifespan)."
else
    echo "RESULT: $FAIL failed requests — the rollout was NOT zero-downtime."
fi
