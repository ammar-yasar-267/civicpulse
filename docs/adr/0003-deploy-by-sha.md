# ADR 0003 — Deploy by immutable reference

- **Status:** accepted
- **Date:** 2026-09-28
- **Deciders:** Muhammad Ammar Yasar

## Context

A tag is a mutable pointer. `:latest` points at whatever was pushed last; `:v1.2` can be moved to
different bytes tomorrow. Nothing in the registry prevents it.

That mutability breaks three things that matter at 3 a.m.:

1. **"What is production running?"** has no answer. `:latest` tells you nothing about which commit
   produced it.
2. **Rollback becomes guesswork.** Re-deploying the previous tag may fetch the same bad bytes, or
   different ones.
3. **Two environments on the same tag can differ.** Staging pulled the tag on Tuesday, prod pulled it
   on Thursday, and the tag moved in between — so "it worked in staging" means nothing.

§3.4 is blunt about it: `:latest` may be pushed, it may never be deployed, and deploying it is an
automatic −8.

## Decision

**Tag with the commit SHA. Deploy by that SHA. Sign the digest.**

Concretely, in `.github/workflows/cd.yml`:

- Every image is pushed as `${{ github.sha }}` **and** `latest`. The SHA tag is what gets deployed;
  `latest` exists only as a convenience pointer for humans doing a manual `docker pull`.
- `k8s/overlays/prod/kustomization.yaml` carries `PLACEHOLDER_TAG`, which the deploy job replaces
  with the commit SHA. The manifests themselves never name a moving tag.
- The `build-push` job emits each image's **digest** as a job output, and `cosign` signs the digest
  rather than the tag — a tag can be moved to different bytes, a digest cannot.
- Every publishing and deploying job is gated with `needs:`. Nothing is published from code that has
  not passed the suite, and nothing is deployed that was not published.

Base images are pinned the same way, by digest:
`python:3.12-slim@sha256:f77ac9e4…`, `nginx:1.27.3-alpine-slim@sha256:5a56ae38…`,
`postgres:16.4-alpine@sha256:5660c2cb…`, `redis:7.4-alpine@sha256:858f009f…`.

So the chain from commit to running bytes is unbroken: a commit SHA names the source, an image
digest names the artefact, and both are recorded in the workflow run summary.

## Consequences

**What this buys.**

- `kubectl -n civicpulse get deploy backend -o jsonpath='{...image}'` returns a SHA that can be
  pasted straight into `git show`. That is the one-word answer §3.4 demands.
- Two rollback mechanisms, both real (see `docs/RUNBOOK.md`):
  - `kubectl rollout undo deployment/backend -n civicpulse` — fast, imperative, ~30 seconds. The
    3 a.m. answer. It does not touch the repository, so the cluster now disagrees with `main`.
  - Re-apply the previous overlay with the previous SHA — slower, declarative, auditable, leaves a
    commit. The correct answer once the fire is out.
- A supply-chain story: SBOMs via Syft, keyless cosign signatures, and Trivy failing the build on
  fixable HIGH/CRITICAL findings.

**What it costs.**

- Nobody can read a SHA. `kubectl describe` output is less human-friendly than `:v1.2.3`, which is
  why `release.yml` also publishes semver tags on `v*` for humans to pin to — while deployment still
  goes by digest.
- Every deploy edits the overlay, so the manifest committed in git contains a placeholder rather than
  the literal deployed value. The deployed value lives in the workflow run and in the cluster. That
  is a deliberate trade: a real GitOps setup would commit the SHA back to the repository, which is
  the next rung (see `docs/ENGINEERING-NOTES.md` Q2).
- Digest-pinned base images do not receive security patches automatically. A patched base is a commit
  and a review — which is the point, but it does require somebody to look.

## Alternatives considered

**Deploy `:latest` and restart.** Rejected: −8, and it makes rollback impossible to reason about.
It is attractive only because it requires no thought.

**Semver tags for deployment.** Better than `:latest`, still mutable — a `v1.2.3` tag can be moved.
Good for humans to *pin* to, wrong as the deployment reference. Hence: semver published, SHA
deployed.

**Deploy by digest everywhere, including in the overlay.** Strictly the strongest option and the
assignment's bonus. Partially adopted — images are signed by digest and the digest is captured as a
job output — but the overlay is pinned by SHA tag rather than digest, because the digest is not known
until after the build, which would mean the deploy job rewriting the overlay with a value that cannot
be reviewed beforehand. A GitOps flow writing the digest back to the repository is the clean way to
close that gap.

**Git tags only, no SHA tags.** Then every merge to `main` would need a release tag to be deployable,
which turns continuous delivery into manual release management.

## Related

- [ADR 0002](0002-frontend-runtime-config.md) — the build-side half: one image, any environment.
- `.github/workflows/cd.yml`, `k8s/overlays/prod/kustomization.yaml`, `docs/RUNBOOK.md`
