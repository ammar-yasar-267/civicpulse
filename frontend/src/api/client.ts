/**
 * Typed API client.
 *
 * The domain types are re-exported from `schema.d.ts`, which is generated from the backend's
 * OpenAPI document (`npm run api:types`). Nothing here hand-copies a field name, so renaming
 * a backend field breaks the build rather than the running page.
 *
 * Two rules this module exists to enforce:
 *
 *  1. The frontend owns no business rules (§2.1). There is no list of valid status
 *     transitions here, no priority ordering, no category inference. The server decides; this
 *     file transports. When the server says 409, we surface its sentence verbatim.
 *  2. Errors arrive as a typed ApiError carrying the server's own message and field list, so
 *     the UI never has to invent "Something went wrong".
 */

import { apiUrl } from './config';
import type { components } from './schema';

export type Complaint = components['schemas']['ComplaintOut'];
export type ComplaintCreate = components['schemas']['ComplaintCreate'];
export type Page = components['schemas']['Page'];
export type Stats = components['schemas']['Stats'];
export type ProvidersMeta = components['schemas']['ProvidersMeta'];
export type ErrorBody = components['schemas']['ErrorBody'];
export type FieldError = components['schemas']['FieldError'];
export type Category = Complaint['category'];
export type Priority = Complaint['priority'];
export type Status = Complaint['status'];

/** Carries the server's own error body so callers can show its message, not a generic one. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: FieldError[];
  readonly retryAfterSeconds?: number;

  constructor(status: number, body: Partial<ErrorBody>, retryAfterSeconds?: number) {
    super(body.detail || `Request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.error || `http_${status}`;
    this.fields = body.fields ?? [];
    this.retryAfterSeconds = retryAfterSeconds;
  }

  /** Field-level messages keyed by field name, for inline form errors. */
  fieldMessages(): Record<string, string> {
    return Object.fromEntries(this.fields.map((f) => [f.field, f.message]));
  }
}

export interface Envelope<T> {
  data: T;
  /** Present on /api/stats: the backend's X-Cache header, rendered in the UI (§2.1). */
  cache?: 'HIT' | 'MISS';
  requestId?: string;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<Envelope<T>> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...init,
      signal,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    });
  } catch (cause) {
    // fetch only rejects on transport failure. Distinguishing it from an HTTP error matters:
    // "the server is unreachable" and "the server said no" need different UI.
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new ApiError(0, {
      error: 'network_error',
      detail: 'Could not reach the CivicPulse API. Check that the backend is running.',
    });
  }

  const cache = response.headers.get('X-Cache');
  const requestId = response.headers.get('X-Request-ID') ?? undefined;

  if (!response.ok) {
    const retryAfter = response.headers.get('Retry-After');
    let body: Partial<ErrorBody> = {};
    try {
      body = (await response.json()) as Partial<ErrorBody>;
    } catch {
      // A proxy or ingress can return HTML on an error; do not let that crash the handler.
      body = { error: `http_${response.status}`, detail: response.statusText };
    }
    throw new ApiError(response.status, body, retryAfter ? Number(retryAfter) : undefined);
  }

  const data = (await response.json()) as T;
  return {
    data,
    cache: cache === 'HIT' || cache === 'MISS' ? cache : undefined,
    requestId,
  };
}

export interface ListParams {
  page?: number;
  pageSize?: number;
  category?: Category | '';
  priority?: Priority | '';
  status?: Status | '';
}

function queryString(params: ListParams): string {
  const search = new URLSearchParams();
  if (params.page) search.set('page', String(params.page));
  if (params.pageSize) search.set('page_size', String(params.pageSize));
  if (params.category) search.set('category', params.category);
  if (params.priority) search.set('priority', params.priority);
  if (params.status) search.set('status', params.status);
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

export const api = {
  submitComplaint(payload: ComplaintCreate, signal?: AbortSignal) {
    return request<Complaint>(
      '/api/complaints',
      { method: 'POST', body: JSON.stringify(payload) },
      signal,
    );
  },

  listComplaints(params: ListParams = {}, signal?: AbortSignal) {
    return request<Page>(`/api/complaints${queryString(params)}`, {}, signal);
  },

  getComplaint(id: string, signal?: AbortSignal) {
    return request<Complaint>(`/api/complaints/${id}`, {}, signal);
  },

  /**
   * Advance a complaint's status. The set of legal targets is deliberately not encoded here —
   * the server owns the state machine, and an invalid move returns a 409 whose message we
   * show as-is.
   */
  updateStatus(id: string, status: Status, signal?: AbortSignal) {
    return request<Complaint>(
      `/api/complaints/${id}/status`,
      { method: 'PATCH', body: JSON.stringify({ status }) },
      signal,
    );
  },

  getStats(signal?: AbortSignal) {
    return request<Stats>('/api/stats', {}, signal);
  },

  getProviders(signal?: AbortSignal) {
    return request<ProvidersMeta>('/api/meta/providers', {}, signal);
  },
};
