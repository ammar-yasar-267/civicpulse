# ADR 0002 — Frontend runtime configuration

- **Status:** accepted
- **Date:** 2026-09-28
- **Deciders:** Muhammad Ammar Yasar

## Context

Vite inlines `import.meta.env.*` into the JavaScript bundle **at build time**. The values become
string literals in the output.

That single fact is the whole problem. If the API base URL is read that way, the built image only
works in the environment it was built for, and:

- dev, staging and prod each need their own image built from identical source;
- the image that was tested is not the image that is deployed;
- rollback means rebuilding rather than re-pointing at a previous digest;
- "what is production running?" stops having a one-word answer.

Build-once-deploy-many would be dead for the frontend, which is the deduction §2.1 is warning about.

## Decision

Resolve the API base URL **at container start**, by two complementary mechanisms.

**1. nginx proxies `/api` to the backend (the primary mechanism).**

The browser only ever talks to the origin that served the page. `frontend/nginx.conf.template`
carries `${BACKEND_URL}`, rendered by `envsubst` when the container starts. The React code requests
relative paths (`/api/stats`), so it needs no backend URL at all — and CORS never applies to the real
deployment, because there is only one origin.

**2. `/config.js`, generated at container start (the escape hatch).**

`frontend/docker-entrypoint.sh` runs as `/docker-entrypoint.d/40-civicpulse-config.sh` and writes:

```js
window.__CIVICPULSE_CONFIG__ = { apiBaseUrl: "", environment: "production" };
```

`index.html` loads it *before* the bundle, and `src/api/config.ts` reads it with a documented
precedence: injected value → same origin. `Cache-Control: no-store` on that one file, or a browser
would keep pointing at yesterday's backend after a redeploy.

This exists so the frontend can be pointed at a backend on a *different* origin — a separate API
domain, a preview environment — without rebuilding. `API_BASE_URL` is empty by default, so the
proxy path is what actually runs.

Both are driven by environment variables on the same image. `import.meta.env` is used **only** for
the Vite dev server, where there is no nginx to proxy.

## Consequences

**What this buys.**

- One image, verified: the same `civicpulse-frontend` image runs under Compose, under kind with
  `BACKEND_URL=http://backend.civicpulse.svc.cluster.local:8000`, and standalone with no backend at
  all. Only env vars differ.
- No secrets in the bundle, structurally. Anything in a browser bundle is public, and "it's
  minified" is not a defence — so the only values that reach the browser are a URL and an
  environment name.
- Rollback is re-pointing at a previous digest.

**What it costs.**

- One extra HTTP request before the app boots, and a hard rule that `/config.js` is never cached.
- A failure mode that must be handled: if `/config.js` 404s, `window.__CIVICPULSE_CONFIG__` is
  undefined. `getConfig()` treats that as same-origin and the app still works — tested in
  `frontend/tests/StatsAndConfig.test.tsx`.
- `envsubst` must be restricted (`NGINX_ENVSUBST_FILTER`), or it would eat nginx's own `$host` and
  `$remote_addr`.

**A defect this surfaced.** Proxying via a literal hostname made nginx resolve `backend` once at
startup and refuse to boot when it did not resolve — so a frontend pod scheduled before the backend
had endpoints crash-looped. The upstream now goes through a variable with a runtime-derived
resolver, so resolution happens per request. Verified: the container serves and returns 502 with no
backend present.

## Alternatives considered

**Bake it in with `import.meta.env` and build per environment.** The thing this ADR exists to
reject. It is the path of least resistance and it destroys build-once-deploy-many.

**Fetch `/config.json` from React before rendering.** Works, but makes every component's first
render depend on an async config load, and there is a visible flash or a spinner before anything
appears. A synchronous `<script>` tag has none of that: by the time the bundle executes, the config
is already on `window`.

**A `<meta>` tag rewritten at start.** Equivalent in effect. Rejected only because rewriting HTML at
container start is more fragile than writing a small separate file — a bad substitution corrupts the
document rather than one script.

**Kubernetes ConfigMap mounted over `/usr/share/nginx/html/config.js`.** Clean on Kubernetes, but it
would mean the Compose path and the Kubernetes path configure the frontend differently. One
mechanism that works everywhere is worth more than a slightly tidier manifest.

## Related

- [ADR 0003](0003-deploy-by-sha.md) — the deploy-side half of build-once-deploy-many.
- `frontend/src/api/config.ts`, `frontend/nginx.conf.template`, `frontend/docker-entrypoint.sh`
