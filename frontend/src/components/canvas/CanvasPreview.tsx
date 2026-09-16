import { useEffect, useState } from "react";
import { useI18n } from "../../i18n";

interface CanvasPreviewProps {
  code: string;
  mode: "react" | "html";
}

const tailwindCdn = '<script src="https://cdn.tailwindcss.com"></script>';

function getReactHtml(code: string) {
  return `<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    ${tailwindCdn}
    <script src="https://unpkg.com/react@18/umd/react.development.js" crossorigin></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js" crossorigin></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
  </head>
  <body>
    <div id="root"></div>
    <script type="text/babel">
      try {
        const { useState, useEffect, useRef, useMemo, useCallback } = React;
        ${code}
        const root = ReactDOM.createRoot(document.getElementById('root'));
        if (typeof App !== 'undefined') {
          root.render(<App />);
        } else if (typeof DefaultComponent !== 'undefined') {
          root.render(<DefaultComponent />);
        } else {
          // If no App, look for the default export or last component
          const comps = Object.keys(window).filter(k => /^[A-Z]/.test(k) && typeof window[k] === 'function');
          if (comps.length > 0) {
            const Comp = window[comps[comps.length - 1]];
            root.render(<Comp />);
          } else {
            document.getElementById('root').innerHTML = '<div style="color:red;padding:20px;">No React component found (expected App).</div>';
          }
        }
      } catch (err) {
        window.parent.postMessage({ type: 'CANVAS_ERROR', message: err.message }, '*');
        document.getElementById('root').innerHTML = '<div style="color:red;padding:20px;">Error: ' + err.message + '</div>';
      }
    </script>
  </body>
</html>`;
}

export default function CanvasPreview({ code, mode }: CanvasPreviewProps) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    const handleMessage = (e: MessageEvent) => {
      if (e.data?.type === "CANVAS_ERROR") {
        setError(e.data.message);
      }
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [code]);

  let srcDoc = code;
  if (mode === "html") {
    if (!code.includes("tailwindcss.com")) {
      srcDoc = code.replace("</head>", `\n${tailwindCdn}\n</head>`);
      if (srcDoc === code) {
        srcDoc = `${tailwindCdn}\n${code}`;
      }
    }
  } else {
    srcDoc = getReactHtml(code);
  }

  return (
    <div className="vsCanvasPreviewContainer" style={{ position: "relative", width: "100%", height: "100%" }}>
      {error && (
        <div className="vsCanvasPreviewError" style={{ position: "absolute", top: 0, left: 0, width: "100%", padding: "16px", background: "rgba(255, 0, 0, 0.1)", color: "red", zIndex: 10 }}>
          {t("预览出错：", "Preview Error: ")} {error}
        </div>
      )}
      <iframe
        key={code}
        srcDoc={srcDoc}
        sandbox="allow-scripts"
        className="vsCanvasPreviewFrame"
        style={{ width: "100%", height: "100%", border: "none", background: "#fff" }}
      />
    </div>
  );
}
