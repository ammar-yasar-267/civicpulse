/**
 * App shell: three views, one tab bar.
 *
 * Deliberately hand-rolled navigation rather than a router. There are exactly three views and
 * no deep-linking requirement in §2.1, and a router would be a dependency carrying no weight.
 */

import { useState } from 'react';
import { ErrorBoundary } from './components/ErrorBoundary';
import { DashboardPage } from './pages/DashboardPage';
import { StatsPage } from './pages/StatsPage';
import { SubmitPage } from './pages/SubmitPage';
import { getConfig } from './api/config';

type View = 'submit' | 'dashboard' | 'stats';

const TABS: { id: View; label: string }[] = [
  { id: 'submit', label: 'Report a problem' },
  { id: 'dashboard', label: 'Operations' },
  { id: 'stats', label: 'Statistics' },
];

export function App() {
  const [view, setView] = useState<View>('submit');
  const { environment } = getConfig();

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <h1>CivicPulse</h1>
          <p className="muted">Municipal complaint intake and triage</p>
        </div>
        {/* Sourced from runtime config, so the same image can announce which environment it is
            running in without a rebuild. */}
        {environment && environment !== 'production' && (
          <span className="badge badge-env">{environment}</span>
        )}
      </header>

      <nav className="tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={view === tab.id}
            className={view === tab.id ? 'tab tab-active' : 'tab'}
            onClick={() => setView(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main>
        {/* Remounts the boundary per view, so recovering from an error on one tab does not
            leave a stale error on another. */}
        <ErrorBoundary key={view}>
          {view === 'submit' && <SubmitPage />}
          {view === 'dashboard' && <DashboardPage />}
          {view === 'stats' && <StatsPage />}
        </ErrorBoundary>
      </main>

      <footer className="muted small">
        CivicPulse · CS4032 Software Construction and Design · triage decisions are made by the
        backend and rendered here
      </footer>
    </div>
  );
}
