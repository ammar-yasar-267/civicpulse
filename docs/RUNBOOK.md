# CivicPulse runbook

For whoever is on call — including me, six months from now, at 3 a.m., having forgotten all of this.

Every command here has been run against the real system. Where a command is destructive it says so
before the command, not after.

---

## 1. Orientation: what is running?

```sh
kubectl -n civicpulse get deploy,statefulset,pods,hpa
kubectl -n civicpulse get deploy backend -o jsonpath='{.spec.template.spec.containers[0].image}'
```

That image reference ends in a **commit SHA**. Paste it straight into `git show` to see exactly
what is deployed:

```sh
git show <sha> --stat
```

This is the payoff from [ADR 0003](adr/0003-deploy-by-sha.md): "what is production running?" has a
one-word answer.

---

## 2. Deploy

### Normal path — merge to `main`

`cd.yml` does it: test → build and push to GHCR tagged with the commit SHA → deploy to the cluster →
wait on rollout → smoke-test the Ingress. Nothing is published from code that failed, and nothing is
deployed that was not published, because every job is gated with `needs:`.

Watch it:

```sh
gh run watch                                  # or: gh run list --workflow=cd.yml
```

### Manual deploy of a specific commit

```sh
cd k8s/overlays/prod
sed -i '' "s|PLACEHOLDER_REGISTRY|ghcr.io/ammar-yasar-267|; s|PLACEHOLDER_TAG|<commit-sha>|" kustomization.yaml
kubectl apply -k .
kubectl -n civicpulse rollout status deployment/backend --timeout=300s
```

**Never deploy `:latest`.** It may be pushed; it may not be deployed. A moving tag makes rollback
guesswork and is an automatic −8.

### First deploy to a fresh cluster

```sh
./scripts/k8s-up.sh
```

Installs the ingress controller and metrics-server, builds and loads the images, creates the
namespace and Secret, applies the overlay, migrates and seeds.

---

## 3. Roll back

Two mechanisms. Use the first during an incident, the second once the fire is out.

### 3a. Fast and imperative — the 3 a.m. answer (~30 seconds)

```sh
kubectl -n civicpulse rollout undo deployment/backend
kubectl -n civicpulse rollout status deployment/backend --timeout=120s
```

Check what you are rolling back *to* first:

```sh
kubectl -n civicpulse rollout history deployment/backend
kubectl -n civicpulse rollout undo deployment/backend --to-revision=3   # a specific one
```

**Cost of this path:** the cluster now disagrees with `main`. Nothing in git records what happened,
and the next `kubectl apply` from CI will happily re-deploy the broken version. It buys time; it
does not resolve anything. Follow it with 3b or with a revert commit.

### 3b. Declarative and auditable — the correct answer

```sh
git log --oneline -20                      # find the last good commit
cd k8s/overlays/prod
sed -i '' "s|PLACEHOLDER_TAG|<previous-good-sha>|" kustomization.yaml
kubectl apply -k .
kubectl -n civicpulse rollout status deployment/backend
```

Better still, revert the offending commit on `main` and let `cd.yml` deploy the revert. Then the
repository and the cluster agree again, and the incident is in the history where the next person can
find it.

### Rolling back a migration

Rolling back application code does **not** roll back the schema. If the bad release included a
migration:

```sh
kubectl -n civicpulse exec deploy/backend -- alembic current
kubectl -n civicpulse exec deploy/backend -- alembic downgrade -1
```

Check `downgrade()` actually does something before relying on it. A migration that dropped a column
cannot give the data back — restore from a backup instead.

---

## 4. Reading logs

Logs are **JSON on stdout**, never a file: a container's filesystem is ephemeral and the log shipper
reads the stream.

```sh
kubectl -n civicpulse logs -l app=backend --tail 100 -f
docker compose logs -f backend            # Compose equivalent
```

Every line carries `request_id`, propagated from `X-Request-ID`. A citizen quoting a reference is
traceable end to end:

```sh
kubectl -n civicpulse logs -l app=backend --tail 5000 | grep '<request-id>'
```

Useful filters:

```sh
# every triage fallback, with the provider and the error class that caused it
kubectl -n civicpulse logs -l app=backend --tail 5000 | grep 'triage fell back'

# just the errors
kubectl -n civicpulse logs -l app=backend --tail 5000 | grep '"level": "ERROR"'

# pretty-print
kubectl -n civicpulse logs -l app=backend --tail 50 | python3 -m json.tool --json-lines
```

---

## 5. When triage starts failing

**Symptom:** complaints still submit (201) but arrive as `triaged_by: "rules:fallback"`, and
classification quality drops.

This is the system working as designed — the fallback is doing its job. It is a degradation, not an
outage. Do not page anyone at 3 a.m. for it.

### Diagnose

```sh
curl -s http://localhost:8080/api/meta/providers | python3 -m json.tool
```

`recent_outcomes` shows the last 20 attempts with provider, latency and whether each fell back. Then
find out *why*:

```sh
kubectl -n civicpulse logs -l app=backend --tail 2000 | grep 'triage fell back'
```

The `error_class` field names the cause:

| `error_class` | Meaning | Action |
|---|---|---|
| `TriageRateLimited` | Free-tier quota exhausted (429) | Expected under load. Wait, or switch to `ollama`. Check the rate limiter is actually protecting `POST /api/complaints`. |
| `TriageTimeout` | Provider exceeded 10 s | Usually provider-side. If persistent, switch provider. |
| `TriageUpstreamError` | Provider 5xx or transport failure | Check the provider's status page. |
| `TriageBadRequest` | 4xx — **usually a bad or revoked API key** | Check the Secret. Not retryable; it will not self-heal. |
| `TriageMalformedOutput` | The model ignored the schema | The guardrail worked. If frequent, the model may have been deprecated — check the model name. |

### Check the key

```sh
kubectl -n civicpulse get secret civicpulse-secrets -o jsonpath='{.data.GROQ_API_KEY}' | base64 -d | head -c 8; echo '...'
```

That prints the first 8 characters only. **Never print a whole key**, and never paste one into a
chat, a ticket or a commit.

Rotate it:

```sh
kubectl -n civicpulse create secret generic civicpulse-secrets \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=GROQ_API_KEY="$NEW_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n civicpulse rollout restart deployment/backend    # env vars are read at startup
```

### Fall back deliberately

To stop calling the third party entirely:

```sh
kubectl -n civicpulse patch configmap civicpulse-config --type merge \
  -p '{"data":{"TRIAGE_PROVIDER":"rules"}}'
kubectl -n civicpulse rollout restart deployment/backend
```

Classification drops to keyword quality. Intake keeps working. This is always safe.

---

## 6. Other common incidents

### `/ready` returns 503

The body names the failed dependency:

```sh
curl -s http://localhost:8000/ready | python3 -m json.tool
```

- `"failed": "postgres"` → `kubectl -n civicpulse get pods -l app=postgres`, then check its logs.
- `"failed": "redis"` → same for redis. The app degrades rather than fails: stats go uncached and
  the rate limiter fails **open**.

Note what does **not** happen: the pods are not restarted. Readiness removes them from the Service;
liveness (`/health`, which touches nothing) keeps them alive so they recover on their own.

### The HPA reports `<unknown>/60%`

```sh
kubectl -n civicpulse get hpa
kubectl -n kube-system get deploy metrics-server
```

Two causes, in order of likelihood:

1. **metrics-server is not running or not ready.** On kind it needs `--kubelet-insecure-tls` because
   the kubelet's serving cert is self-signed. `scripts/k8s-up.sh` patches this.
2. **A container has no `resources.requests.cpu`.** The HPA computes utilisation as
   usage ÷ request; with no request there is no denominator. This is a three-line block, and its
   absence is the most common cause of a "broken HPA".

### Pods are stuck in `ContainerCreating`

```sh
kubectl -n civicpulse describe pod <pod> | tail -20
```

If the events mention image pulling, the node is fetching the image — on a slow link this takes
minutes. Pre-pull it:

```sh
docker exec civicpulse-control-plane crictl pull <image>
```

If they mention a missing Secret, the Secret was not created. See §2.

### The database pod was deleted

Nothing to do. The PVC outlives the pod; the StatefulSet recreates `postgres-0` and it remounts the
same volume. Verified — see [`docs/evidence/k8s-deployment.txt`](evidence/k8s-deployment.txt).

```sh
kubectl -n civicpulse get pvc     # pgdata-postgres-0 should still be Bound
```

### A citizen reports a complaint "disappeared"

```sh
kubectl -n civicpulse exec postgres-0 -- psql -U civicpulse -d civicpulse \
  -c "SELECT id, category, priority, status, triaged_by, created_at FROM complaints ORDER BY created_at DESC LIMIT 20;"
```

Check the status — a complaint moved to `rejected` is still there, just filtered out of the default
dashboard view.

---

## 7. Routine operations

```sh
# Re-seed (idempotent — running it twice changes nothing)
kubectl -n civicpulse exec deploy/backend -- python -m app.seed

# Apply a new migration
kubectl -n civicpulse exec deploy/backend -- alembic upgrade head

# Back up the database
kubectl -n civicpulse exec postgres-0 -- pg_dump -U civicpulse civicpulse | gzip > backup-$(date +%F).sql.gz

# Scale manually (the HPA will take over again within its stabilisation window)
kubectl -n civicpulse scale deployment/backend --replicas=4

# Watch a rollout
kubectl -n civicpulse rollout status deployment/backend -w
```

### Draining a node

The PodDisruptionBudget (`minAvailable: 1`) makes this safe — pods are evicted one at a time rather
than together:

```sh
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
```

---

## 8. Escalation

There is no on-call rotation; this is a university assignment. For a real deployment this section
would name who to wake and when. The honest version:

| Severity | Example | Response |
|---|---|---|
| Degraded | Triage falling back to rules | Next working day. Intake still works. |
| Serious | `/ready` 503 across all pods | Immediate — citizens cannot submit. |
| Critical | Data loss, or a leaked credential | Immediate. Rotate the credential, write an incident note (§5.3 requires one). |

## Related

- [`docs/ENGINEERING-NOTES.md`](ENGINEERING-NOTES.md) — why the system is built this way
- [ADR 0003](adr/0003-deploy-by-sha.md) — why rollback works at all
