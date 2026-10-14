import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import ErrorBoundary from "./components/ErrorBoundary";
import HostedRoot from "./components/HostedRoot";
import { IS_HOSTED_BUILD } from "./hosted";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      {IS_HOSTED_BUILD ? <HostedRoot /> : <App />}
    </ErrorBoundary>
  </React.StrictMode>
);
