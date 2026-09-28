#!/usr/bin/env bash
# Runs the k6 load profile while capturing the HPA's reaction, and writes the evidence the rubric
# asks for: `kubectl get hpa -w` output plus a replicas-vs-load time series.
#
#   scripts/load-test.sh
#
# Produces, in docs/evidence/:
#   hpa-watch.txt         raw `kubectl get hpa -w` capture
#   hpa-timeseries.csv    seconds,replicas,cpu_utilisation,offered_vus — the chart's data
#   k6-summary.txt        the k6 run summary
#   hpa-lag.md            the measured lag, which is §5.2 Q5
#
# The lag between load arriving and replicas rising is the point of the exercise, so the sampler
# runs at 1s and timestamps everything against a single t0.
set -uo pipefail

NS=civicpulse
EVIDENCE=docs/evidence
BASE_URL="${BASE_URL:-http://localhost}"
HOST_HEADER="${HOST_HEADER:-civicpulse.local}"

mkdir -p "$EVIDENCE" load/results

command -v k6 >/dev/null || { echo "k6 is not installed: brew install k6" >&2; exit 1; }
kubectl -n "$NS" get hpa backend-hpa >/dev/null 2>&1 || {
    echo "backend-hpa not found. Run scripts/k8s-up.sh first." >&2; exit 1; }

# The HPA cannot scale on a metric nothing is serving. Fail early and clearly rather than producing
# a flat chart and a confusing conclusion.
if kubectl -n "$NS" get hpa backend-hpa -o jsonpath='{.status.currentMetrics}' 2>/dev/null | grep -q 'null'; then
    echo "warning: the HPA has no metrics yet. Is metrics-server ready?" >&2
    kubectl -n kube-system get deploy metrics-server 2>/dev/null || true
    echo "waiting 30s for the first metrics scrape..." >&2
    sleep 30
fi

echo "==> baseline"
kubectl -n "$NS" get hpa backend-hpa
START_REPLICAS=$(kubectl -n "$NS" get deploy backend -o jsonpath='{.spec.replicas}')
echo "    starting replicas: $START_REPLICAS"

T0=$(date +%s)

# ---- watcher: the raw capture the rubric asks to submit -------------------
kubectl -n "$NS" get hpa backend-hpa -w > "$EVIDENCE/hpa-watch.txt" 2>&1 &
WATCH_PID=$!

# ---- sampler: structured time series for the chart ------------------------
(
    echo "seconds,replicas,ready_replicas,cpu_utilisation_pct,offered_vus"
    while true; do
        now=$(date +%s)
        elapsed=$((now - T0))

        replicas=$(kubectl -n "$NS" get deploy backend -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "")
        ready=$(kubectl -n "$NS" get deploy backend -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)
        cpu=$(kubectl -n "$NS" get hpa backend-hpa \
                -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}' 2>/dev/null || echo "")

        # Offered load, derived from the k6 stage profile in load/k6-script.js so the chart can plot
        # load and capacity on one timeline.
        if   [ "$elapsed" -lt 30  ]; then vus=5
        elif [ "$elapsed" -lt 60  ]; then vus=$(( 5 + (elapsed - 30) * 55 / 30 ))
        elif [ "$elapsed" -lt 240 ]; then vus=60
        elif [ "$elapsed" -lt 300 ]; then vus=$(( 60 - (elapsed - 240) * 60 / 60 ))
        else vus=0
        fi

        echo "${elapsed},${replicas:-},${ready:-0},${cpu:-},${vus}"
        sleep 1
    done
) > "$EVIDENCE/hpa-timeseries.csv" &
SAMPLE_PID=$!

cleanup() {
    kill "$WATCH_PID" "$SAMPLE_PID" 2>/dev/null || true
    wait "$WATCH_PID" "$SAMPLE_PID" 2>/dev/null || true
}
trap cleanup EXIT

# ---- the load itself ------------------------------------------------------
echo "==> running k6 (5 minutes)"
BASE_URL="$BASE_URL" HOST_HEADER="$HOST_HEADER" \
    k6 run load/k6-script.js 2>&1 | tee "$EVIDENCE/k6-summary.txt"

# Let scaleDown's stabilisation window start to show in the capture.
echo "==> holding 60s to observe scale-down behaviour"
sleep 60

cleanup
trap - EXIT

# ---- analysis: the lag, which is the learning outcome --------------------
echo "==> computing the scale-out lag"
python3 - "$EVIDENCE/hpa-timeseries.csv" "$START_REPLICAS" <<'PY' | tee "$EVIDENCE/hpa-lag.md"
import csv, sys, statistics

path, start = sys.argv[1], int(sys.argv[2])
rows = []
with open(path) as fh:
    for r in csv.DictReader(fh):
        try:
            rows.append({
                "t": int(r["seconds"]),
                "replicas": int(r["replicas"]) if r["replicas"] else None,
                "ready": int(r["ready_replicas"] or 0),
                "cpu": int(r["cpu_utilisation_pct"]) if r["cpu_utilisation_pct"] else None,
                "vus": int(r["offered_vus"]),
            })
        except ValueError:
            continue

if not rows:
    print("no samples captured"); raise SystemExit(1)

RAMP_START = 30           # k6 begins ramping at t=30s (see load/k6-script.js)
first_scale = next((r for r in rows if r["replicas"] and r["replicas"] > start), None)
first_ready = next((r for r in rows if r["ready"] > start), None)
peak = max((r["replicas"] or 0) for r in rows)
peak_cpu = max((r["cpu"] or 0) for r in rows)
cpus = [r["cpu"] for r in rows if r["cpu"] is not None]

print("# HPA scale-out lag (measured)\n")
print(f"- starting replicas: **{start}**, peak replicas: **{peak}**")
print(f"- peak observed CPU utilisation: **{peak_cpu}%** (target 60%)")
if cpus:
    print(f"- median CPU utilisation during the run: **{statistics.median(cpus):.0f}%**")

if first_scale:
    decision_lag = first_scale["t"] - RAMP_START
    print(f"- load began rising at t={RAMP_START}s; the HPA changed the replica count at "
          f"t={first_scale['t']}s → **decision lag ≈ {decision_lag}s**")
else:
    print("- the HPA never scaled. Check that metrics-server is ready and that "
          "resources.requests.cpu is set — with no request there is no denominator.")

if first_ready:
    capacity_lag = first_ready["t"] - RAMP_START
    print(f"- the first NEW pod became Ready at t={first_ready['t']}s → "
          f"**capacity lag ≈ {capacity_lag}s**")
    if first_scale:
        print(f"- of which **{first_ready['t'] - first_scale['t']}s** was pod startup "
              f"(schedule → image → uvicorn boot → readiness probe passing)")

print("""
## Where the time goes

1. **Metrics staleness** — metrics-server scrapes on an interval (15s by default) and reports a
   short rolling window, so the utilisation the HPA reads already describes the recent past.
2. **HPA sync period** — the controller re-evaluates every 15s (`--horizontal-pod-autoscaler-sync-period`),
   so a decision can wait up to one full period after the metric is available.
3. **Pod startup** — schedule, pull (or find) the image, start uvicorn, then pass the readiness
   probe before the Service will route to it.

## What would reduce it

Shorten the metrics scrape interval and the HPA sync period (at the cost of more API traffic and
more flapping); keep the image small and warm on the node so startup is short; lower the target
utilisation so scaling begins earlier; or pre-warm with a higher `minReplicas`.

## Why this matters

The lag is why autoscaling is not a substitute for capacity planning. For the roughly one minute
between load arriving and capacity arriving, the pods already running absorb everything — so
`minReplicas` has to be large enough to survive the burst on its own, and the HPA handles the
sustained level rather than the spike.
""")
PY

echo
echo "==> evidence written to $EVIDENCE/"
ls -la "$EVIDENCE"
echo
echo "Final HPA state:"
kubectl -n "$NS" get hpa backend-hpa
kubectl -n "$NS" get pods -l app=backend
