/**
 * Stats view (§2.1).
 *
 * Renders aggregates, and renders the system's own cache behaviour from the X-Cache header.
 * Showing your cache state in the UI is unusual — and it is the thing that makes the 30s TTL
 * and the invalidate-on-write rule visible instead of theoretical: submit a complaint, come
 * back here, and the badge reads MISS because the write invalidated the entry.
 *
 * It also surfaces /api/meta/providers, so the measured triage cache hit rate and the last
 * triage outcomes are on screen rather than buried in a log.
 */

import { useCallback, useEffect, useState } from 'react';
import { ApiError, api, type ProvidersMeta, type Stats } from '../api/client';
import { ProviderBadge } from '../components/ProviderBadge';

function BarRow({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="bar-row">
      <span className="bar-label">{label}</span>
      <span className="bar-track">
        <span className="bar-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="bar-value">{value}</span>
    </div>
  );
}

function Breakdown({ title, counts }: { title: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = entries.length > 0 ? entries[0][1] : 0;
  return (
    <div className="breakdown">
      <h3>{title}</h3>
      {entries.length === 0 ? (
        <p className="muted">No data yet.</p>
      ) : (
        entries.map(([label, value]) => (
          <BarRow key={label} label={label} value={value} max={max} />
        ))
      )}
    </div>
  );
}

export function StatsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [cache, setCache] = useState<'HIT' | 'MISS' | undefined>();
  const [meta, setMeta] = useState<ProvidersMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [statsResult, metaResult] = await Promise.all([
        api.getStats(signal),
        api.getProviders(signal),
      ]);
      setStats(statsResult.data);
      setCache(statsResult.cache);
      setMeta(metaResult.data);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setError(err instanceof ApiError ? err.message : 'Could not load statistics.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return (
    <section className="page">
      <header className="page-header">
        <h2>Statistics</h2>
        <div className="stats-head">
          {cache && (
            <span
              className={`badge badge-cache badge-cache-${cache.toLowerCase()}`}
              data-testid="cache-badge"
              title={
                cache === 'HIT'
                  ? 'Served from the Redis cache (30s TTL).'
                  : 'Computed from Postgres — the cache was empty or was invalidated by a write.'
              }
            >
              X-Cache: {cache}
            </span>
          )}
          <button onClick={() => void load()} disabled={loading}>
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </header>

      {error && (
        <p role="alert" className="banner banner-error">
          {error}
        </p>
      )}

      {stats && (
        <>
          <p className="total" data-testid="stats-total">
            <strong>{stats.total}</strong> complaints recorded
          </p>
          <div className="breakdowns">
            <Breakdown title="By category" counts={stats.by_category} />
            <Breakdown title="By priority" counts={stats.by_priority} />
            <Breakdown title="By status" counts={stats.by_status} />
          </div>
        </>
      )}

      {meta && (
        <div className="provider-panel">
          <h3>Triage</h3>
          <p>
            Active provider: <ProviderBadge triagedBy={meta.active_provider as never} />
          </p>
          <p className="muted">
            Triage cache: {meta.cache_hits} hits / {meta.cache_misses} misses —{' '}
            <strong>{(meta.cache_hit_rate * 100).toFixed(1)}% hit rate</strong>
          </p>
          {meta.recent_outcomes.length > 0 && (
            <table className="outcomes">
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Latency</th>
                  <th>Fallback</th>
                  <th>Cached</th>
                </tr>
              </thead>
              <tbody>
                {meta.recent_outcomes.slice(0, 10).map((o, i) => (
                  <tr key={`${o.at}-${i}`}>
                    <td>{o.provider}</td>
                    <td>{o.latency_ms} ms</td>
                    <td>{o.fallback ? 'yes' : 'no'}</td>
                    <td>{o.cached ? 'yes' : 'no'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}
