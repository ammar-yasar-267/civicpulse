/**
 * Shows which reader classified a complaint, and how long it took.
 *
 * Surfacing `triaged_by` in the UI is required by §2.1, and it is the most useful thing on the
 * screen when the hosted provider is having a bad day: "rules:fallback" tells an operator
 * immediately that classifications are currently keyword-quality, without reading a log.
 */

import type { Complaint } from '../api/client';

const LABELS: Record<Complaint['triaged_by'], string> = {
  'llm:groq': 'Groq (hosted LLM)',
  'llm:ollama': 'Ollama (local LLM)',
  rules: 'Keyword rules',
  'rules:fallback': 'Keyword rules (LLM fallback)',
  simulated: 'Simulated (CI)',
};

export function ProviderBadge({
  triagedBy,
  latencyMs,
}: {
  triagedBy: Complaint['triaged_by'];
  latencyMs?: number;
}) {
  const isFallback = triagedBy === 'rules:fallback';
  return (
    <span
      className={`badge badge-provider${isFallback ? ' badge-provider-fallback' : ''}`}
      data-testid="provider-badge"
      title={
        isFallback
          ? 'The language model was unavailable, so keyword rules classified this complaint.'
          : undefined
      }
    >
      {LABELS[triagedBy] ?? triagedBy}
      {typeof latencyMs === 'number' && latencyMs > 0 && (
        <span className="muted"> · {latencyMs} ms</span>
      )}
    </span>
  );
}
