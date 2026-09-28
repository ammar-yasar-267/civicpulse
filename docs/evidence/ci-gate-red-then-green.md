# Evidence: a red pipeline blocks the merge, then green

Rubric I asks for evidence that the gate actually works, rather than a workflow file that would
work in principle. This is a real failure from this repository, not a contrived one.

## Red

**Run:** [36469500500](https://github.com/ammar-yasar-267/civicpulse/actions/runs/36469500500)
**Job:** `lint and type check` → step `ruff (format)`
**Result:** ❌ failure, 17s

```
Would reformat: app/logging_setup.py
1 file would be reformatted, 44 files already formatted
##[error]Process completed with exit code 1.
```

### What actually caused it

While removing a dead `_RESERVED` constant from `backend/app/logging_setup.py`, the edit was made
with a regex substitution rather than by hand, and it left a formatting artefact that `ruff format`
disagreed with. Local `ruff check` passed — lint and format are separate checks, and only the
format check catches this.

This is a small defect, and that is the point: it is exactly the class of thing a human reviewer
skims past and a pipeline does not. It reached the branch because `ruff format` had last been run
before those files were edited.

### The gate held

The failing job blocked subsequent jobs through `needs:`, so `build`, `scan` and `integration` never
ran. Nothing was built or published from a commit that had already failed a check — which is the
whole reason those jobs declare `needs:`.

## Green

**Run:** [36472704688](https://github.com/ammar-yasar-267/civicpulse/actions/runs/36472704688)
**Result:** ✅ all seven jobs pass.

```
✓ backend tests            43s
✓ validate k8s manifests   10s
✓ frontend tests           20s
✓ lint and type check      52s
✓ build images (no push)   1m45s
✓ trivy image scan         36s
✓ compose integration smoke 1m7s
```

## Three more real failures the gate caught on the way

The formatting failure above was the first. Getting to green took three more, none of them
contrived:

| # | Failure | Cause | Fix |
|---|---|---|---|
| 2 | `compose integration smoke` — `limiter returns 429 under a burst` | The integration job set `RATE_LIMIT_REQUESTS=1000` so load would not be throttled, while `verify-stack.sh` fired 15 requests expecting a 429. The assertion was right; the environment contradicted it. | The check now reads the limit back from `X-RateLimit-Limit` and bursts `limit+3`; CI uses a limit low enough to exercise the limiter. |
| 3 | `trivy image scan` — failed at **Set up job**, 2s | `aquasecurity/trivy-action@0.28.0` does not exist — the tags carry a `v` prefix and that number was never released. **Nothing had ever been scanned.** | Install a pinned Trivy binary directly; the tool version is now part of the repository. |
| 4 | `trivy image scan` — real vulnerabilities, once it actually ran | `starlette` SSRF + DoS; `zlib`, `musl`, `openssl` in the nginx base. | FastAPI 0.115.6 → 0.141.1 (starlette 1.7.0); nginx base bumped and package set upgraded at build time. |
| 5 | `backend tests` — OpenAPI drift check | FastAPI 0.141 emits `ctx`/`input` on `ValidationError` that 0.115 did not, so the committed schema and generated frontend types went stale. | Regenerated both. |

Failure 3 is the one worth dwelling on. The scan job had been **green-adjacent** — it was failing,
but at setup, so it had never examined an image. Fixing the version turned a job that did nothing
into a job that found five real CVEs. A check that cannot fail for the right reason is worse than no
check, because it buys false confidence.

## Screenshots

`docs/evidence/ci-red.png` and `docs/evidence/ci-green.png` — the blocked merge button and the
passing checks, captured from the PR page.

> **To capture:** open PR #8, screenshot the red check with the merge button disabled, then
> screenshot the same PR after the fix with all checks green.
