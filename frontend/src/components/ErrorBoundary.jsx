import { Component } from "react";

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("UI render failed", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="page-stack">
          <div className="error-block">
            <strong>Interface render failed.</strong>
            <span>{this.state.error.message || "Unexpected frontend error."}</span>
            <button type="button" className="ghost-button" onClick={() => this.setState({ error: null })}>
              Try again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
