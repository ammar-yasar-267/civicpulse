/**
 * Dashboard tests.
 *
 * The one that matters for the rubric is the 409: the server's sentence must reach the screen
 * unchanged, because "an invalid transition must surface the server's 409 message, not a
 * generic error" (§2.1).
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DashboardPage } from '../src/pages/DashboardPage';

const COMPLAINT = {
  id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  text: 'Burst water main flooding Street 12 since fajr.',
  location: 'Street 12, Gulberg III, Lahore',
  reporter_contact: null,
  category: 'water',
  priority: 'high',
  status: 'open',
  ai_summary: 'Street 12: burst main flooding ground floors',
  triaged_by: 'rules:fallback',
  triage_latency_ms: 4,
  created_at: '2026-09-28T10:00:00Z',
  updated_at: '2026-09-28T10:00:00Z',
};

const PAGE = { items: [COMPLAINT], total: 1, page: 1, page_size: 10 };

const CONFLICT_MESSAGE =
  'Invalid transition open -> resolved. Allowed from open: in_progress, rejected.';

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return {
    ok: status < 400,
    status,
    statusText: 'stubbed',
    headers: { get: (name: string) => headers[name] ?? null },
    json: async () => body,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('DashboardPage', () => {
  it('renders a complaint with its triage provider', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(200, PAGE)));
    render(<DashboardPage />);

    expect(await screen.findByText(/burst main flooding ground floors/i)).toBeInTheDocument();
    expect(screen.getByText('1 complaints')).toBeInTheDocument();
    // Fallback is visible to the operator without reading a log.
    expect(screen.getByTestId('provider-badge')).toHaveTextContent(/LLM fallback/i);
  });

  it("surfaces the server's 409 message verbatim on an invalid transition", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, PAGE))
      .mockResolvedValueOnce(
        jsonResponse(409, {
          error: 'invalid_transition',
          detail: CONFLICT_MESSAGE,
          fields: [{ field: 'status', message: CONFLICT_MESSAGE }],
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<DashboardPage />);

    await screen.findByText(/burst main flooding/i);
    await user.selectOptions(screen.getByLabelText(/change status for/i), 'resolved');

    const error = await screen.findByTestId('transition-error');
    expect(error).toHaveTextContent(CONFLICT_MESSAGE);
  });

  it('applies a legal transition to the row', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, PAGE))
      .mockResolvedValueOnce(jsonResponse(200, { ...COMPLAINT, status: 'in_progress' }));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<DashboardPage />);

    await screen.findByText(/burst main flooding/i);
    await user.selectOptions(screen.getByLabelText(/change status for/i), 'in_progress');

    await waitFor(() => {
      expect(screen.getByTestId('status-badge')).toHaveTextContent('in progress');
    });
  });

  it('sends filter values as query parameters', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, PAGE));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<DashboardPage />);

    await screen.findByText(/burst main flooding/i);
    await user.selectOptions(screen.getByLabelText('Category'), 'water');

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes('category=water'))).toBe(true);
    });
  });

  it('reports an unreachable API instead of rendering an empty table', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    render(<DashboardPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach/i);
  });
});
