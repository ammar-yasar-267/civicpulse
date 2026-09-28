/**
 * Submit view (§2.1).
 *
 * Client-side validation mirrors the server rules without replacing them: the same 10–2000 and
 * 3–200 bounds, checked here for fast feedback, and checked again by Pydantic because a
 * browser check is a courtesy and not a guarantee. When the server disagrees, its field-level
 * messages win and are shown inline.
 *
 * The loading state is honest (§2.1): AI triage takes seconds, so the button says what is
 * happening rather than pretending the request is instant.
 */

import { useRef, useState } from 'react';
import { ApiError, api, type Complaint, type ComplaintCreate } from '../api/client';
import { ProviderBadge } from '../components/ProviderBadge';
import { PriorityBadge } from '../components/Badges';

const TEXT_MIN = 10;
const TEXT_MAX = 2000;
const LOCATION_MIN = 3;
const LOCATION_MAX = 200;

/** Mirrors the server's constraints. Returns field -> message, empty when valid. */
export function validate(values: ComplaintCreate): Record<string, string> {
  const errors: Record<string, string> = {};
  const text = values.text.trim();
  const location = values.location.trim();

  if (text.length < TEXT_MIN) {
    errors.text = `Please describe the problem in at least ${TEXT_MIN} characters.`;
  } else if (text.length > TEXT_MAX) {
    errors.text = `Please keep the description under ${TEXT_MAX} characters.`;
  }

  if (location.length < LOCATION_MIN) {
    errors.location = `Location needs at least ${LOCATION_MIN} characters.`;
  } else if (location.length > LOCATION_MAX) {
    errors.location = `Location must be under ${LOCATION_MAX} characters.`;
  }

  return errors;
}

export function SubmitPage() {
  const [text, setText] = useState('');
  const [location, setLocation] = useState('');
  const [contact, setContact] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<Complaint | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const payload: ComplaintCreate = {
      text,
      location,
      reporter_contact: contact.trim() ? contact.trim() : null,
    };

    const clientErrors = validate(payload);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      setFormError(null);
      return;
    }

    setErrors({});
    setFormError(null);
    setSubmitting(true);
    setResult(null);

    abortRef.current?.abort();
    abortRef.current = new AbortController();

    try {
      const { data } = await api.submitComplaint(payload, abortRef.current.signal);
      setResult(data);
      setText('');
      setLocation('');
      setContact('');
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      if (error instanceof ApiError) {
        // The server's own messages, verbatim — including the 429's Retry-After.
        setErrors(error.fieldMessages());
        setFormError(
          error.status === 429 && error.retryAfterSeconds
            ? `${error.message} (retry in ${error.retryAfterSeconds}s)`
            : error.message,
        );
      } else {
        setFormError('Unexpected error submitting the complaint.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="page">
      <header className="page-header">
        <h2>Report a problem</h2>
        <p className="muted">
          Describe the issue in your own words. Our system reads it and routes it to the right
          department — you do not need to pick a category.
        </p>
      </header>

      <form onSubmit={onSubmit} noValidate>
        <div className="field">
          <label htmlFor="text">What is the problem?</label>
          <textarea
            id="text"
            name="text"
            rows={5}
            value={text}
            onChange={(e) => setText(e.target.value)}
            aria-invalid={Boolean(errors.text)}
            aria-describedby={errors.text ? 'text-error' : 'text-hint'}
            placeholder="Burst water main flooding Street 12 since fajr, water entering ground floors"
          />
          <div className="field-foot">
            {errors.text ? (
              <span id="text-error" role="alert" className="error">
                {errors.text}
              </span>
            ) : (
              <span id="text-hint" className="muted">
                {text.trim().length}/{TEXT_MAX} characters
              </span>
            )}
          </div>
        </div>

        <div className="field">
          <label htmlFor="location">Where is it?</label>
          <input
            id="location"
            name="location"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            aria-invalid={Boolean(errors.location)}
            aria-describedby={errors.location ? 'location-error' : undefined}
            placeholder="Street 12, Gulberg III, Lahore"
          />
          {errors.location && (
            <span id="location-error" role="alert" className="error">
              {errors.location}
            </span>
          )}
        </div>

        <div className="field">
          <label htmlFor="contact">
            Your phone or email <span className="muted">(optional)</span>
          </label>
          <input
            id="contact"
            name="reporter_contact"
            value={contact}
            onChange={(e) => setContact(e.target.value)}
            aria-invalid={Boolean(errors.reporter_contact)}
            placeholder="0300-1234567"
          />
          {errors.reporter_contact && (
            <span role="alert" className="error">
              {errors.reporter_contact}
            </span>
          )}
        </div>

        {formError && (
          <p role="alert" className="banner banner-error">
            {formError}
          </p>
        )}

        <button type="submit" disabled={submitting} className="primary">
          {/* Honest loading state: triage is a network call to a language model. */}
          {submitting ? 'Reading your complaint…' : 'Submit complaint'}
        </button>
        {submitting && (
          <p className="muted" aria-live="polite">
            Classifying the report — this usually takes a few seconds.
          </p>
        )}
      </form>

      {result && (
        <div className="result-card" role="status">
          <h3>Complaint recorded</h3>
          <p className="muted">
            Reference <code>{result.id}</code>
          </p>
          <dl className="result-grid">
            <div>
              <dt>Category</dt>
              <dd data-testid="result-category">{result.category}</dd>
            </div>
            <div>
              <dt>Priority</dt>
              <dd>
                <PriorityBadge priority={result.priority} />
              </dd>
            </div>
            <div>
              <dt>Triaged by</dt>
              <dd>
                <ProviderBadge triagedBy={result.triaged_by} latencyMs={result.triage_latency_ms} />
              </dd>
            </div>
          </dl>
          <blockquote data-testid="result-summary">{result.ai_summary}</blockquote>
        </div>
      )}
    </section>
  );
}
