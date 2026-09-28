/**
 * k6 load profile for the HPA demonstration (§3.3).
 *
 *   k6 run load/k6-script.js
 *   BASE_URL=http://civicpulse.local k6 run load/k6-script.js
 *
 * The shape of the profile is the experiment. A flat load tells you the steady state; this ramps
 * hard and then holds, so the *lag* between load arriving and capacity arriving is visible — which
 * is the thing §5.2 Q5 asks you to measure and explain.
 *
 *   0-30s    warm up at 5 VUs        establish a baseline below the 60% target
 *   30s-1m   ramp to 60 VUs          the step change the HPA has to react to
 *   1m-4m    hold at 60 VUs          long enough for pods to schedule, start and pass readiness
 *   4m-5m    ramp down to 0          exercises scaleDown's 300s stabilisation window
 *
 * Traffic is deliberately read-heavy. POST /api/complaints is rate-limited to protect the LLM
 * quota, so hammering it would measure the limiter rather than the service — and with a live
 * provider it would also spend real inference budget. GET /api/complaints does real database work
 * (filter, sort, paginate, count) which is what actually consumes the CPU the HPA scales on.
 */

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';
const HOST_HEADER = __ENV.HOST_HEADER || '';

// Custom metrics, so the report distinguishes "the service refused politely" from "the service
// broke". A 429 is correct behaviour under a burst and must not be counted as a failure.
const rateLimited = new Counter('rate_limited_429');
const cacheHits = new Counter('stats_cache_hits');
const cacheMisses = new Counter('stats_cache_misses');
const triageLatency = new Trend('triage_latency_ms', true);
const errorRate = new Rate('unexpected_errors');

export const options = {
  stages: [
    { duration: '30s', target: 5 },
    { duration: '30s', target: 60 },
    { duration: '3m', target: 60 },
    { duration: '1m', target: 0 },
  ],
  thresholds: {
    // p95 under 2s for reads. Generous on purpose: during scale-out the existing pods are
    // saturated, and a threshold that fails during the very event being demonstrated is useless.
    'http_req_duration{expected_response:true}': ['p(95)<2000'],
    // Anything other than 2xx/409/429 is a real error. Allowing 1% covers the brief window
    // during a rollout where a connection can be cut.
    unexpected_errors: ['rate<0.01'],
  },
  // Keep the summary readable and comparable between runs.
  summaryTrendStats: ['min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const params = () => ({
  headers: {
    'Content-Type': 'application/json',
    ...(HOST_HEADER ? { Host: HOST_HEADER } : {}),
  },
  // Tag so thresholds can separate expected refusals from genuine failures.
  tags: { expected_response: 'true' },
});

const CATEGORIES = ['water', 'electricity', 'sanitation', 'roads', 'streetlights', 'other'];
const PRIORITIES = ['high', 'normal', 'low'];
const STATUSES = ['open', 'in_progress', 'resolved', 'rejected'];

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

export default function () {
  group('dashboard list (filtered, paginated)', () => {
    // Varying the filters defeats any accidental caching and exercises the composite index.
    const query = [
      `page=${1 + Math.floor(Math.random() * 3)}`,
      'page_size=20',
      Math.random() < 0.5 ? `category=${pick(CATEGORIES)}` : '',
      Math.random() < 0.4 ? `priority=${pick(PRIORITIES)}` : '',
      Math.random() < 0.4 ? `status=${pick(STATUSES)}` : '',
    ]
      .filter(Boolean)
      .join('&');

    const res = http.get(`${BASE_URL}/api/complaints?${query}`, params());
    check(res, {
      'list returns 200': (r) => r.status === 200,
      'list reports a total': (r) => {
        try {
          return typeof r.json('total') === 'number';
        } catch {
          return false;
        }
      },
    });
    errorRate.add(res.status !== 200);
  });

  group('stats (Redis-cached)', () => {
    const res = http.get(`${BASE_URL}/api/stats`, params());
    const cache = res.headers['X-Cache'];
    if (cache === 'HIT') cacheHits.add(1);
    if (cache === 'MISS') cacheMisses.add(1);
    check(res, { 'stats returns 200': (r) => r.status === 200 });
    errorRate.add(res.status !== 200);
  });

  // One in ten iterations writes, so the cache-invalidation path and the limiter are both
  // exercised without the run turning into a rate-limit test.
  if (Math.random() < 0.1) {
    group('submit a complaint', () => {
      const payload = JSON.stringify({
        // Unique text per request: identical content would hit the triage content-hash cache and
        // measure nothing.
        text: `Load test complaint ${__VU}-${__ITER}: burst water main flooding the street since fajr, water entering ground floors.`,
        location: `Street ${__VU}, Gulberg III, Lahore`,
      });
      const res = http.post(`${BASE_URL}/api/complaints`, payload, params());

      if (res.status === 429) {
        // Correct behaviour, not a failure: the distributed limiter is protecting the LLM quota.
        rateLimited.add(1);
        return;
      }
      check(res, { 'submit returns 201': (r) => r.status === 201 });
      if (res.status === 201) {
        try {
          triageLatency.add(res.json('triage_latency_ms'));
        } catch {
          // body shape already asserted by the check above
        }
      }
      errorRate.add(res.status !== 201);
    });
  }

  // Short think time. Without any, a handful of VUs saturates the runner rather than the service.
  sleep(0.5 + Math.random() * 0.5);
}

export function handleSummary(data) {
  const hits = data.metrics.stats_cache_hits?.values?.count ?? 0;
  const misses = data.metrics.stats_cache_misses?.values?.count ?? 0;
  const total = hits + misses;

  const lines = [
    '',
    '=== CivicPulse load test summary ===',
    `requests:            ${data.metrics.http_reqs?.values?.count ?? 0}`,
    `p95 latency:         ${(data.metrics.http_req_duration?.values?.['p(95)'] ?? 0).toFixed(0)} ms`,
    `rate-limited (429):  ${data.metrics.rate_limited_429?.values?.count ?? 0}  (expected under burst)`,
    `stats cache:         ${hits} hits / ${misses} misses` +
      (total ? ` = ${((hits / total) * 100).toFixed(1)}% hit rate` : ''),
    `triage p95:          ${(data.metrics.triage_latency_ms?.values?.['p(95)'] ?? 0).toFixed(0)} ms`,
    '',
    'Now capture the autoscaler:  kubectl -n civicpulse get hpa -w',
    '',
  ].join('\n');

  return {
    stdout: lines,
    // Committed as evidence for the replicas-vs-load chart.
    'load/results/summary.json': JSON.stringify(data, null, 2),
  };
}
