/**
 * Submit view component tests.
 *
 * fetch is stubbed rather than a real backend being called: these assert the component's
 * contract with the API, and a component test that needs a database is an integration test
 * wearing the wrong hat (the real request path is covered by the Compose integration job).
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SubmitPage, validate } from '../src/pages/SubmitPage';

const TRIAGED_COMPLAINT = {
  id: '3f6c2b1e-0b7a-4a1d-9f2e-1c2d3e4f5a6b',
  text: 'Burst water main flooding Street 12 since fajr, water entering ground floors.',
  location: 'Street 12, Gulberg III, Lahore',
  reporter_contact: null,
  category: 'water',
  priority: 'high',
  status: 'open',
  ai_summary: 'Street 12: burst main flooding ground floors',
  triaged_by: 'llm:groq',
  triage_latency_ms: 812,
  created_at: '2026-09-28T10:00:00Z',
  updated_at: '2026-09-28T10:00:00Z',
};

function mockFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: 'stubbed',
    headers: { get: (name: string) => headers[name] ?? null },
    json: async () => body,
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('validate', () => {
  it('mirrors the server bounds without replacing them', () => {
    expect(validate({ text: 'too short', location: 'Lahore', reporter_contact: null }).text).toBeTruthy();
    expect(validate({ text: 'a'.repeat(2001), location: 'Lahore', reporter_contact: null }).text).toBeTruthy();
    expect(validate({ text: 'a'.repeat(50), location: 'xx', reporter_contact: null }).location).toBeTruthy();
    expect(validate({ text: 'a'.repeat(50), location: 'Lahore', reporter_contact: null })).toEqual({});
  });
});

describe('SubmitPage', () => {
  it('blocks submission and shows inline errors when input is too short', async () => {
    const fetchMock = mockFetch(201, TRIAGED_COMPLAINT);
    const user = userEvent.setup();
    render(<SubmitPage />);

    await user.type(screen.getByLabelText(/what is the problem/i), 'short');
    await user.click(screen.getByRole('button', { name: /submit complaint/i }));

    // Both fields are invalid here (the location was never filled in), so both report.
    const alerts = await screen.findAllByRole('alert');
    const messages = alerts.map((a) => a.textContent).join(' | ');
    expect(messages).toMatch(/at least 10 characters/i);
    expect(messages).toMatch(/location needs at least 3/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('renders category, priority, summary and provider from the response', async () => {
    mockFetch(201, TRIAGED_COMPLAINT);
    const user = userEvent.setup();
    render(<SubmitPage />);

    await user.type(
      screen.getByLabelText(/what is the problem/i),
      'Burst water main flooding Street 12 since fajr, water entering ground floors.',
    );
    await user.type(screen.getByLabelText(/where is it/i), 'Street 12, Gulberg III, Lahore');
    await user.click(screen.getByRole('button', { name: /submit complaint/i }));

    expect(await screen.findByTestId('result-category')).toHaveTextContent('water');
    expect(screen.getByTestId('priority-badge')).toHaveTextContent('high');
    expect(screen.getByTestId('result-summary')).toHaveTextContent('burst main flooding');
    // The provider that produced the classification is shown, per §2.1.
    expect(screen.getByTestId('provider-badge')).toHaveTextContent(/Groq/);
    expect(screen.getByTestId('provider-badge')).toHaveTextContent('812 ms');
  });

  it('shows an honest loading state while triage is in flight', async () => {
    // A promise that never settles, standing in for a slow LLM call.
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})));
    const user = userEvent.setup();
    render(<SubmitPage />);

    await user.type(
      screen.getByLabelText(/what is the problem/i),
      'Garbage not lifted for ten days near the corner point, smell is unbearable.',
    );
    await user.type(screen.getByLabelText(/where is it/i), 'Allama Iqbal Town, Lahore');
    await user.click(screen.getByRole('button', { name: /submit complaint/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /reading your complaint/i })).toBeDisabled();
    });
    expect(screen.getByText(/usually takes a few seconds/i)).toBeInTheDocument();
  });

  it("surfaces the server's field-level 400 messages", async () => {
    mockFetch(400, {
      error: 'validation_error',
      detail: 'The submitted complaint failed validation.',
      fields: [{ field: 'location', message: 'Location is not recognised in this municipality.' }],
    });
    const user = userEvent.setup();
    render(<SubmitPage />);

    await user.type(
      screen.getByLabelText(/what is the problem/i),
      'Street light not working in our lane for one month now.',
    );
    await user.type(screen.getByLabelText(/where is it/i), 'Somewhere else entirely');
    await user.click(screen.getByRole('button', { name: /submit complaint/i }));

    expect(
      await screen.findByText(/not recognised in this municipality/i),
    ).toBeInTheDocument();
  });

  it('surfaces a 429 with the Retry-After value', async () => {
    mockFetch(
      429,
      { error: 'rate_limited', detail: 'Rate limit of 10 requests exceeded.', fields: [] },
      { 'Retry-After': '42' },
    );
    const user = userEvent.setup();
    render(<SubmitPage />);

    await user.type(
      screen.getByLabelText(/what is the problem/i),
      'Gutter is overflowing on the main road and water is standing for a week.',
    );
    await user.type(screen.getByLabelText(/where is it/i), 'Orangi Town, Karachi');
    await user.click(screen.getByRole('button', { name: /submit complaint/i }));

    expect(await screen.findByText(/retry in 42s/i)).toBeInTheDocument();
  });
});
