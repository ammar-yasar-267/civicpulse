# AI usage disclosure

Per §5.5: honest attribution, not avoidance. Specific disclosure carries no penalty; presenting
AI-generated work as original work does. This document is deliberately specific, because "AI
assisted with some parts" is not a disclosure.

## Tool

**Claude Code** (Anthropic), Claude Opus, used interactively from the terminal across two working
sessions on 2026-09-28/29. No other AI tool was used.

## How this was built

I worked with Claude Code in a directed loop: I set the target and the order of work, it produced
code, we ran it, and the failures drove the next round of changes. Most of the source text was
AI-generated. The decisions about what to build, in what order, and what "done" meant were mine, and
several of the defects listed below were caught because I pushed on something that looked finished
but was not.

### What the AI generated

| Area | Extent |
|---|---|
| `backend/app/**` | Generated — layering, provider seam, orchestrator, routes, schemas |
| `backend/tests/**` | Generated, including the fakes and the mandatory fallback test |
| `backend/alembic/**` | Generated, then corrected (defect 1) |
| `frontend/src/**`, `frontend/tests/**` | Generated |
| `Dockerfile` ×2, `compose*.yaml` | Generated, then corrected (defects 4, 5, 8) |
| `k8s/**`, `.github/workflows/**`, `scripts/**` | Generated |
| `docs/**` | Drafted from the real session transcript, then reviewed and corrected by me |

### What I directed and decided

Not code, but not nothing — these shaped what the code is:

- **Scope and order.** I set the build order against the rubric's own priority (F → C → I → H) and
  decided what to sacrifice under a hard deadline.
- **I caught the one-command gap.** The quickstart was four commands — copy `.env`, compose up, then
  two `docker compose exec` calls — and had been written off as done. I asked whether §1.4's
  one-command requirement was actually met. It was not. That question produced the `migrate` service,
  the dev defaults, and the CI job that now proves a clean clone works. It was a −5 deduction sitting
  in plain sight.
- **Infrastructure and accounts.** Repository owner, private visibility, Groq as the hosted provider,
  and the key itself.
- **Course-policy judgement.** The partner situation, and how the collaboration rubric items would be
  handled honestly rather than simulated with a second account.
- **Review and redirection.** I interrupted and redirected the work repeatedly — including pausing it
  when usage ran high, and changing the model and effort level partway through.

### What is entirely mine

- The demo video and the screenshots in `docs/evidence/` (other than the scripted captures produced
  by `scripts/verify-stack.sh`, `scripts/load-test.sh` and `scripts/rollout-demo.sh`).
- The answers in `docs/ENGINEERING-NOTES.md` — drafted from this session's real commands and
  failures, then reviewed and taken over by me. Q8's failure is a real failure from this build.

## The defects, and why they matter

The generated code did not work first time. Every one of these came from running the thing, and they
are the most useful record of what was actually understood versus what was merely produced.

1. **Alembic emitted `CREATE TYPE` twice.** `create_table()` re-creates enum types unless the column
   declares `create_type=False`, so `alembic upgrade head` died with `DuplicateObject`. It presented
   as intermittent, because a half-failed run leaves orphaned types and no `alembic_version` row.
2. **`alembic/env.py` ignored a caller-supplied URL,** so the test suite's throwaway database was
   bypassed and migrations aimed at a host that does not resolve locally.
3. **`"not urgent"` scored as HIGH priority.** The keyword reader matched `urgent` inside `not
   urgent`. Fixed by collapsing negated forms before the high-signal scan.
4. **Fabricated identifiers.** The AI invented plausible-looking image digests and an `apt` pin
   (`curl=7.88.1-10+deb12u12`) that did not exist; the builds failed with errors that read like
   network problems. Real digests came from `docker buildx imagetools inspect`. **This is the failure
   mode to watch for in generated infrastructure code: confident, correctly-shaped identifiers that
   are entirely fictional.**
5. **The frontend image crash-looped without a backend.** nginx resolves a literal `proxy_pass`
   hostname once at boot, so a frontend pod scheduled before the backend had endpoints would never
   start.
6. **nginx overwrote the caller's `X-Request-ID`,** breaking request tracing exactly at the proxy.
7. **The submission linter had two false positives of its own** — healthcheck loopback URLs read as
   service-to-service `localhost`, and `uvicorn[standard]` truncated the lock-file comparison.
8. **Trivy had never scanned anything.** The job referenced an action version that does not exist and
   failed at *setup*, so it looked like a scan step while examining no images. Fixing the version
   surfaced five real CVEs (Starlette SSRF and DoS; `zlib`, `musl`, `openssl` in the nginx base), all
   since remediated.

Defect 8 is the one worth dwelling on, and it generalises beyond this assignment: a check that cannot
fail for the right reason is worse than no check, because it buys false confidence.

## On the viva

§5.5 notes the viva does not care who wrote a line, only whether it can be defended. That is the
standard I have prepared against. The commentary throughout this codebase exists for that reason —
every non-obvious decision carries its reasoning inline, so the code reads as an argument rather than
as an artefact, and the trade-offs in the four ADRs are written with their costs stated, not just
their benefits.

## Verification

Nothing here is claimed without a command that demonstrates it:

- `scripts/verify-stack.sh` — 31 assertions against the running stack
- `backend/tests/` — 91 tests, 84% coverage · `frontend/tests/` — 19 component tests
- `scripts/check_submission.py` — lints for the §5.3 automatic deductions (0 errors)
- `docs/evidence/` — HPA scale-out capture, zero-downtime rollout, CI red-then-green history
