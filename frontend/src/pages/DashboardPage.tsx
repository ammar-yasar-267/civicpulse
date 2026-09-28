/**
 * Operations dashboard (§2.1).
 *
 * Paginated, filterable, and able to advance status. The important detail is the failure path:
 * when an operator attempts an illegal transition the server returns 409 with a sentence
 * naming the attempted move, and that sentence is rendered verbatim. Replacing it with
 * "Error updating status" would throw away the only information that tells the operator what
 * to do instead.
 *
 * Note what is absent: no list of legal transitions. The dropdown offers every status and lets
 * the server rule, which keeps one source of truth for the state machine.
 */

import { useCallback, useEffect, useState } from 'react';
import { ApiError, api, type Complaint, type ListParams, type Page, type Status } from '../api/client';
import { CategoryBadge, PriorityBadge, StatusBadge } from '../components/Badges';
import { ProviderBadge } from '../components/ProviderBadge';

const PAGE_SIZE = 10;
const ALL_STATUSES: Status[] = ['open', 'in_progress', 'resolved', 'rejected'];

export function DashboardPage() {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<ListParams>({ category: '', priority: '', status: '' });
  const [data, setData] = useState<Page | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Keyed by complaint id so one row's 409 does not blank another row's message.
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [updating, setUpdating] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setLoadError(null);
      try {
        const { data: result } = await api.listComplaints(
          { ...filters, page, pageSize: PAGE_SIZE },
          signal,
        );
        setData(result);
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setLoadError(error instanceof ApiError ? error.message : 'Could not load complaints.');
      } finally {
        setLoading(false);
      }
    },
    [filters, page],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function changeStatus(complaint: Complaint, next: Status) {
    setUpdating(complaint.id);
    setRowErrors((prev) => ({ ...prev, [complaint.id]: '' }));
    try {
      const { data: updated } = await api.updateStatus(complaint.id, next);
      setData((prev) =>
        prev
          ? { ...prev, items: prev.items.map((c) => (c.id === updated.id ? updated : c)) }
          : prev,
      );
    } catch (error) {
      if (error instanceof ApiError) {
        // The server's 409 message, exactly as sent.
        setRowErrors((prev) => ({ ...prev, [complaint.id]: error.message }));
      }
    } finally {
      setUpdating(null);
    }
  }

  function updateFilter(key: keyof ListParams, value: string) {
    setPage(1); // a filter change invalidates the current page number
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <section className="page">
      <header className="page-header">
        <h2>Operations dashboard</h2>
        <p className="muted">{data ? `${data.total} complaints` : 'Loading…'}</p>
      </header>

      <div className="filters">
        <label>
          Category
          <select
            value={filters.category ?? ''}
            onChange={(e) => updateFilter('category', e.target.value)}
          >
            <option value="">All</option>
            {['water', 'electricity', 'sanitation', 'roads', 'streetlights', 'other'].map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          Priority
          <select
            value={filters.priority ?? ''}
            onChange={(e) => updateFilter('priority', e.target.value)}
          >
            <option value="">All</option>
            {['high', 'normal', 'low'].map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={filters.status ?? ''}
            onChange={(e) => updateFilter('status', e.target.value)}
          >
            <option value="">All</option>
            {ALL_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>

      {loadError && (
        <p role="alert" className="banner banner-error">
          {loadError}
        </p>
      )}

      {loading && <p aria-live="polite">Loading complaints…</p>}

      {!loading && data?.items.length === 0 && (
        <p className="muted">No complaints match these filters.</p>
      )}

      {data && data.items.length > 0 && (
        <table className="complaints">
          <thead>
            <tr>
              <th>Complaint</th>
              <th>Category</th>
              <th>Priority</th>
              <th>Status</th>
              <th>Triaged by</th>
              <th>Advance</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((c) => (
              <tr key={c.id}>
                <td>
                  <p className="summary">{c.ai_summary ?? c.text.slice(0, 90)}</p>
                  <p className="muted small">{c.location}</p>
                  {rowErrors[c.id] && (
                    <p role="alert" className="error small" data-testid="transition-error">
                      {rowErrors[c.id]}
                    </p>
                  )}
                </td>
                <td>
                  <CategoryBadge category={c.category} />
                </td>
                <td>
                  <PriorityBadge priority={c.priority} />
                </td>
                <td>
                  <StatusBadge status={c.status} />
                </td>
                <td>
                  <ProviderBadge triagedBy={c.triaged_by} latencyMs={c.triage_latency_ms} />
                </td>
                <td>
                  <select
                    aria-label={`Change status for ${c.id}`}
                    value=""
                    disabled={updating === c.id}
                    onChange={(e) => {
                      const next = e.target.value as Status;
                      if (next) void changeStatus(c, next);
                      e.target.value = '';
                    }}
                  >
                    <option value="">
                      {updating === c.id ? 'Updating…' : 'Change to…'}
                    </option>
                    {/* Every status is offered; the server decides which are legal. */}
                    {ALL_STATUSES.filter((s) => s !== c.status).map((s) => (
                      <option key={s} value={s}>
                        {s.replace('_', ' ')}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <nav className="pager">
        <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
          Previous
        </button>
        <span>
          Page {page} of {totalPages}
        </span>
        <button onClick={() => setPage((p) => p + 1)} disabled={page >= totalPages}>
          Next
        </button>
      </nav>
    </section>
  );
}
