# Evidence: the two-command bar in §1.4

> *"A stranger clones your repository and, with one command, has the whole system running with
> seeded data. A second command puts it on a Kubernetes cluster."*

Both tested from a **clean checkout of `origin/dev`** into an empty directory — no `.env`, no
pre-built images, no cached cluster. A `.env` is deliberately absent, because that is exactly what a
stranger gets.

## Command 1 — the whole system, locally

```sh
docker compose up -d --build
```

**Result: exit 0 in 17.8 seconds.**

```
seeded complaints : 36
categories        : water 8, sanitation 7, electricity 10, other 3, roads 5, streetlights 3
frontend          : HTTP 200
submit a complaint: water/high via rules
```

No migrate step and no seed step, because a one-shot `migrate` service does both: it waits for
Postgres to report healthy, applies the Alembic migrations, runs the idempotent seed, and exits. The
backend declares `depends_on: migrate: {condition: service_completed_successfully}`, so it never
serves a request against a schema that does not exist yet.

It classifies via `rules` rather than a hosted model, which is correct: a clean clone has no API key,
and the system is designed to work without one.

## Command 2 — onto Kubernetes

```sh
./scripts/k8s-up.sh
```

**Result: exit 0, unattended.**

```
deployment.apps/backend    2/2
deployment.apps/frontend   1/1
deployment.apps/redis      1/1
statefulset.apps/postgres  1/1

through the Ingress:
  frontend : HTTP 200
  api      : HTTP 200
  seeded   : 36 complaints
  submit   : sanitation/high
```

The script creates the kind cluster, installs the two things a bare cluster lacks but this deployment
needs (an ingress controller, and metrics-server patched with `--kubelet-insecure-tls` so the HPA has
metrics at all), builds and loads the images, creates the namespace and Secret, applies the overlay,
then migrates and seeds.

## A defect this test found

The first attempts at command 2 failed, and only one of the two causes was environmental:

1. **A real race.** The script waited with `kubectl wait --for=condition=ready pod`, which fails with
   `no matching resources found` when it runs before the ReplicaSet has created the pod — a race lost
   roughly half the time on a fresh cluster. Fixed by waiting on
   `rollout status deployment/ingress-nginx-controller` instead, which handles pod creation.
2. **Slow image pulls**, on a link that was also timing out against Docker Hub that evening. Not a
   script defect, and it did not recur.

The run recorded above is after the fix and was completed start to finish with no intervention.
