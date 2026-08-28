import { Component, type ErrorInfo, type ReactNode } from "react";

type ErrorBoundaryProps = {
  children: ReactNode;
};

type ErrorBoundaryState = {
  error: Error | null;
};

/**
 * Last line of defense against render-time crashes. Without a boundary the
 * whole SPA white-screens on any uncaught rendering error, forcing the user
 * to reload manually and losing whatever they were doing. This catches those
 * errors and offers a recovery screen instead.
 *
 * Kept dependency-free (inline styles, no hooks) on purpose: it must render
 * even when everything else in the tree is broken.
 */
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Keep the stack in the console for debugging; no telemetry yet.
    console.error("Echo render error:", error, info.componentStack);
  }

  private handleRetry = (): void => {
    try {
      sessionStorage.removeItem("vs_chunk_retry_pending");
    } catch {
      // Ignore
    }
    this.setState({ error: null });
  };

  private handleReload = (): void => {
    try {
      sessionStorage.removeItem("vs_chunk_retry_pending");
    } catch {
      // Ignore
    }
    window.location.reload();
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) {
      return this.props.children;
    }

    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "24px",
          background: "var(--vs-bg, #f6f7fb)",
          color: "var(--vs-text, #1f2430)",
          fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif",
        }}
      >
        <div
          style={{
            maxWidth: 560,
            width: "100%",
            padding: "28px 32px",
            borderRadius: 14,
            background: "var(--vs-card-bg, #ffffff)",
            boxShadow: "0 12px 32px rgba(15, 23, 42, 0.12)",
          }}
        >
          <h1 style={{ margin: "0 0 8px", fontSize: 20 }}>界面渲染出错了</h1>
          <p style={{ margin: "0 0 16px", fontSize: 14, opacity: 0.75 }}>
            Something went wrong while rendering the app. Your data and
            settings are not affected.
          </p>
          <pre
            style={{
              margin: "0 0 20px",
              padding: "12px 14px",
              borderRadius: 8,
              background: "rgba(220, 38, 38, 0.08)",
              color: "#b91c1c",
              fontSize: 12,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              maxHeight: 160,
              overflow: "auto",
            }}
          >
            {error.message || String(error)}
          </pre>
          <div style={{ display: "flex", gap: 12 }}>
            <button
              type="button"
              onClick={this.handleRetry}
              style={{
                padding: "8px 18px",
                borderRadius: 8,
                border: "1px solid rgba(15, 23, 42, 0.15)",
                background: "transparent",
                cursor: "pointer",
                fontSize: 14,
              }}
            >
              重试 / Retry
            </button>
            <button
              type="button"
              onClick={this.handleReload}
              style={{
                padding: "8px 18px",
                borderRadius: 8,
                border: "none",
                background: "#2563eb",
                color: "#ffffff",
                cursor: "pointer",
                fontSize: 14,
              }}
            >
              重新加载 / Reload
            </button>
          </div>
        </div>
      </div>
    );
  }
}
