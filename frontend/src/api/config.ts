/**
 * Runtime configuration (§2.1 — "the part most students get wrong").
 *
 * A Vite build inlines `import.meta.env` values into the static bundle at BUILD time. If the
 * API URL were read that way, the resulting image would only work in the environment it was
 * built for, and build-once-deploy-many would be dead for the frontend: dev, staging and prod
 * would each need their own image built from identical source.
 *
 * So the base URL is resolved at RUNTIME, in this order:
 *
 *   1. `window.__CIVICPULSE_CONFIG__.apiBaseUrl` — injected by /config.js, which
 *      docker-entrypoint.sh writes from environment variables when the container starts. One
 *      image, any environment, no rebuild.
 *   2. `""` (same origin) — the default, because nginx proxies /api to the backend. The
 *      browser then never needs to know a backend URL at all, and CORS never enters into it.
 *
 * `import.meta.env` is used only for the Vite dev server, where there is no nginx to proxy.
 * See docs/adr/0002-frontend-runtime-config.md.
 */

export interface RuntimeConfig {
  apiBaseUrl: string;
  environment: string;
}

declare global {
  interface Window {
    __CIVICPULSE_CONFIG__?: Partial<RuntimeConfig>;
  }
}

function readInjectedConfig(): Partial<RuntimeConfig> {
  // Defensive: /config.js is a separate request and may 404 in a misconfigured deploy. The
  // app must still render and talk to its own origin rather than crash on boot.
  if (typeof window === 'undefined') return {};
  return window.__CIVICPULSE_CONFIG__ ?? {};
}

export function getConfig(): RuntimeConfig {
  const injected = readInjectedConfig();

  // Dev-server fallback only. In a container this is always undefined, because the built
  // bundle has no .env file behind it.
  const devBase = import.meta.env?.VITE_DEV_API_BASE_URL as string | undefined;

  return {
    apiBaseUrl: injected.apiBaseUrl ?? devBase ?? '',
    environment: injected.environment ?? import.meta.env?.MODE ?? 'unknown',
  };
}

/** Join the runtime base with a path, tolerating a trailing slash on either side. */
export function apiUrl(path: string): string {
  const base = getConfig().apiBaseUrl.replace(/\/$/, '');
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${base}${suffix}`;
}
