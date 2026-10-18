import { Component, type ErrorInfo, type ReactNode } from "react";
export class ErrorBoundary extends Component<
  { children: ReactNode; resetKey?: string },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // Deliberately omit error text and component props: they may contain patient data.
    window.dispatchEvent(
      new CustomEvent("application-error", {
        detail: { kind: "render_failure" },
      }),
    );
  }
  componentDidUpdate(
    previous: Readonly<{ children: ReactNode; resetKey?: string }>,
  ) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey)
      this.setState({ failed: false });
  }
  render() {
    return this.state.failed ? (
      <section className="card padded error-state" role="alert">
        <h1>This page couldn’t be displayed.</h1>
        <p>
          Reload to reconnect. Any unsaved changes may need to be entered again.
        </p>
        <div className="actions">
          <button className="button primary" onClick={() => location.reload()}>
            Reload application
          </button>
          <a className="button" href="/dashboard/overview">
            Go to overview
          </a>
        </div>
      </section>
    ) : (
      this.props.children
    );
  }
}
