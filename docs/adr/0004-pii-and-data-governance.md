# ADR 0004 — PII and data governance in the triage path

- **Status:** accepted
- **Date:** 2026-09-28
- **Deciders:** Muhammad Ammar Yasar

## Context

A municipal complaint is not neutral text. Real ones read like this — these are from our own seed
corpus, which was written to be realistic:

> "Burst water main flooding Street 12 since fajr, water is entering ground floor of three houses.
> Please send team urgently, we have shifted children upstairs." — *Street 12, Gulberg III, Lahore*,
> contact `0300-1234567`

That is a **street address, a phone number, and a statement about who is inside a specific building
right now**. Under Pakistan's PECA framework and the draft Personal Data Protection Bill, and under
GDPR-style reasoning generally, that is personal data and some of it is sensitive.

When `TRIAGE_PROVIDER=llm`, the complaint text and location are sent to a third party over the
internet. The brief points at the specific hazard (§2.5): Google's free Gemini tier states that
inputs may be used to improve its models. Groq's free tier is gated by rate limits rather than a
stated training-data claim, but "free tier, no credit card" is not a data processing agreement, and I
should not assume favourable terms I have not been given in writing.

So there is a real decision: what leaves this machine, to whom, and why that is acceptable.

## Decision

**Send the minimum needed to classify. Never send the contact field. Default to not sending anything
at all.**

Four parts:

**1. `reporter_contact` is never sent to any LLM.** It is not an input to classification — a phone
number does not help decide whether a complaint is about water or roads. The prompt builder
(`backend/app/providers/triage/prompt.py`) takes only `text` and `location`; there is no code path
that passes the contact to a provider. This is the single highest-value control here, because a phone
number is the field that makes a complaint *identifying* rather than merely *locating*.

**2. Complaint text and location ARE sent, and this is the accepted exposure.** They cannot be
withheld, because they are the classification signal. A redacted complaint is an unclassifiable
complaint: strip "Street 12" and the summary is useless to the crew being dispatched.

**3. The default provider is `rules`, not `llm`.** `.env.example` ships `TRIAGE_PROVIDER=rules` and
`k8s/overlays/dev` pins `rules`. Nothing leaves the machine unless somebody deliberately configures a
hosted provider. `OllamaTriage` exists as a fully offline path with the same interface, so the
zero-egress option is a one-variable change rather than a rewrite.

**4. Cache keys are hashes, not content.** `triage_cache_key()` normalises and SHA-256s the text, so
complaint bodies never appear in Redis keys where an operator running `KEYS *` would see them.
Tested in `backend/tests/test_cache_and_ratelimit.py`.

### What actually leaves the machine, precisely

| Field | Sent to the LLM? | Reason |
|---|---|---|
| `text` | **Yes** | The classification signal. Cannot be withheld. |
| `location` | **Yes** | Needed for the summary and for urgency (a burst main at a school differs from one in an empty lot). |
| `reporter_contact` | **No** | Not a classification input. Highest re-identification risk. |
| `id`, `created_at`, `status` | No | Server-side only; not in the prompt. |

Transport is HTTPS to `api.groq.com`. The API key comes from the environment — `.env` locally
(gitignored), a Kubernetes Secret in the cluster, GitHub Secrets in CI — and is never logged: the
`LLMTriage` error paths deliberately do not interpolate the request into exception messages, because
an exception string ends up in a log line.

## Consequences

**What this buys.**

- The most identifying field never crosses the boundary, by construction rather than by policy.
- A deployment can be made zero-egress with one environment variable, and the `internal: true`
  Docker network means the database and cache have no route to the internet at all.
- Honest disclosure is possible: this table is what I would show a data-protection reviewer.

**What it costs and what remains exposed.**

- **Street-level addresses still go to a third party.** A complaint mentioning a specific house, plus
  a timestamp, is potentially re-identifying even without a phone number. I am accepting this, not
  eliminating it.
- Free-tier terms can change, and a free tier gives no contractual recourse. This is documented
  rather than solved.
- Complaint text is stored in Postgres in plaintext, with no field-level encryption and no retention
  policy. For a real municipal system both would be required; here the volume is a demo dataset and
  the scope is the assignment.
- No citizen consent flow exists. A real deployment needs the submission form to state that the text
  is processed by an automated system, and ideally to offer a path that does not use one.

## Alternatives considered

**Redact PII before sending (regex over phone numbers and house numbers).** Tempting and I rejected
it: regex redaction over Urdu-influenced English gives a false sense of safety. It would miss
`0300 1234567`, `three double zero`, and "the house next to Al-Madina bakery" — which is a perfectly
good re-identifier and unmatchable by pattern. Shipping a control that appears to work but does not is
worse than an honest, documented exposure. If redaction were required, it would need a named-entity
model, which means sending the text to a model to avoid sending the text to a model.

**Ollama only, no hosted provider ever.** The strongest privacy position, and genuinely viable: no
key, no egress, no third party. Rejected as the default because the brief requires a hosted path to be
demonstrated and because a 1B model on laptop CPU classifies noticeably worse — which is itself the
buy-versus-host lesson (CLO 4), measured in `docs/TRIAGE.md` rather than asserted.

**Send only the first sentence.** Cheaper and marginally less exposure, but it degrades classification
on exactly the complaints that matter — the long, detailed, urgent ones — while still sending the
address.

**Ask the citizen for consent per submission.** The right answer for production. Out of scope here,
and noted as a gap rather than quietly omitted.

## Related

- [ADR 0001](0001-provider-interface.md) — the seam that makes the offline path a one-variable change.
- `backend/app/providers/triage/prompt.py`, `backend/app/providers/cache.py`
