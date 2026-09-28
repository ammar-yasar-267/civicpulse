# HPA scale-out lag (measured)

- starting replicas: **2**, peak replicas: **8**
- peak observed CPU utilisation: **187%** (target 60%)
- median CPU utilisation during the run: **50%**
- load began rising at t=30s; the HPA changed the replica count at t=70s → **decision lag ≈ 40s**
- the first NEW pod became Ready at t=73s → **capacity lag ≈ 43s**
- of which **3s** was pod startup (schedule → image → uvicorn boot → readiness probe passing)

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

