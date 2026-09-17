import { useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n";

interface CanvasPreviewProps {
  code: string;
  mode: "react" | "html";
}

const tailwindCdn = '<script src="https://cdn.tailwindcss.com"></script>';

function getReactHtml(code: string) {
  // Keep generated source out of the surrounding script's HTML parser.
  const source = JSON.stringify(code).replace(/</g, "\\u003c");
  return `<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    ${tailwindCdn}
    <script src="https://unpkg.com/react@18/umd/react.development.js" crossorigin></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js" crossorigin></script>
    <script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
  </head>
  <body>
    <div id="root"></div>
    <script>
      function reportError(error) {
        const message = String(error && error.message || error);
        window.parent.postMessage({ type: 'CANVAS_ERROR', message }, '*');
        document.getElementById('root').textContent = 'Error: ' + message;
      }
      window.addEventListener('error', event => reportError(event.error || event.message));
      window.addEventListener('unhandledrejection', event => reportError(event.reason));
      try {
        // Compile as a module before evaluating: wrapping export/import in a
        // try block makes otherwise valid generated components a syntax error.
        const compiled = Babel.transform(${source}, {
          filename: 'canvas.jsx',
          presets: ['react'],
          plugins: ['transform-modules-commonjs'],
        }).code;
        const module = { exports: {} };
        const require = name => {
          if (name === 'react') return React;
          if (name === 'react-dom' || name === 'react-dom/client') return ReactDOM;
          throw new Error('Unsupported canvas import: ' + name + '. Use a self-contained component.');
        };
        const evaluate = new Function('React', 'require',
          'const { useState, useEffect, useRef, useMemo, useCallback } = React;\\n' +
          'return function(module, exports) {\\n' +
          compiled + '\\n;return module.exports.default || (typeof App !== "undefined" ? App : ' +
          '(typeof DefaultComponent !== "undefined" ? DefaultComponent : null));\\n};');
        const Component = evaluate(React, require)(module, module.exports);
        if (!Component) throw new Error('No React component found (expected a default export or App).');
        const root = ReactDOM.createRoot(document.getElementById('root'));
        root.render(React.createElement(Component));
      } catch (err) {
        reportError(err);
      }
    </script>
  </body>
</html>`;
}

export default function CanvasPreview({ code, mode }: CanvasPreviewProps) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    setError(null);
    const handleMessage = (e: MessageEvent) => {
      if (e.source === frameRef.current?.contentWindow && e.data?.type === "CANVAS_ERROR" && typeof e.data.message === "string") {
        setError(e.data.message);
      }
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [code, mode]);

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
        ref={frameRef}
        title={t("画布预览", "Canvas preview")}
        key={`${mode}:${code}`}
        srcDoc={srcDoc}
        sandbox="allow-scripts"
        className="vsCanvasPreviewFrame"
        style={{ width: "100%", height: "100%", border: "none", background: "#fff" }}
      />
    </div>
  );
}
