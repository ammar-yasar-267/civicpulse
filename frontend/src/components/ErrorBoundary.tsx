/**
 * Error boundary (§2.1 required engineering).
 *
 * Without one, a render-time exception anywhere in the tree unmounts the whole app and the
 * citizen gets a blank white page — the least debuggable failure mode there is. This keeps the
 * shell alive, says what happened, and offers a way back.
 *
 * Boundaries only catch errors thrown during render, lifecycle and constructors. Rejected
 * promises in event handlers are handled where they occur (see the try/catch in each page).
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Goes to the browser console, which is where a developer looks first. Deliberately not
    // shipped anywhere: there is no error-reporting service configured, and pretending
    // otherwise would be worse than being honest about it.
    console.error('Unhandled render error:', error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="page" role="alert">
        <h2>Something broke in the interface</h2>
        <p>
          The page failed to render. Your submitted complaints are unaffected — this is a
          display problem, not a data problem.
        </p>
        <pre className="error-detail">{error.message}</pre>
        <button className="primary" onClick={() => this.setState({ error: null })}>
          Try again
        </button>
      </div>
    );
  }
}
