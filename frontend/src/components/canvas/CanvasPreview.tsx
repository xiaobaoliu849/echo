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
    <script src="https://unpkg.com/react@18/umd/react.development.js" crossorigin onload="window.react = window.React"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js" crossorigin></script>
    <script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js"></script>
    <script src="https://unpkg.com/lucide-react@0.577.0/dist/umd/lucide-react.js" crossorigin></script>
  </head>
  <body>
    <div id="root"></div>
    <script>
      function reportError(error) {
        const message = String(error && error.message || error);
        window.parent.postMessage({ type: 'CANVAS_ERROR', message }, '*');
        document.getElementById('root').textContent = '';
      }
      window.addEventListener('error', event => reportError(event.error || event.message));
      window.addEventListener('unhandledrejection', event => reportError(event.reason));
      // Generated code often names icons that lucide-react doesn't ship
      // (e.g. "Waveform"); one undefined element type would otherwise blank
      // the whole preview, so unknown icons fall back to a generic one.
      // Read the UMD global by name, like React/ReactDOM/Babel below.
      const lucideBase = (typeof LucideReact !== 'undefined' && LucideReact) || window.LucideReact || {};
      const lucideFallback = lucideBase.CircleDashed || lucideBase.Circle || (() => null);
      const LucideIcons = new Proxy(lucideBase, {
        get(target, prop) {
          // The UMD build has no __esModule marker; without it Babel's
          // "import * as Icons" copies only the known icons and loses the
          // fallback.
          if (prop === '__esModule') return true;
          if (prop in target) return target[prop];
          if (typeof prop === 'string' && /^[A-Z]/.test(prop)) return lucideFallback;
          return undefined;
        },
      });
      // Last resort for any other undefined component: render a visible
      // placeholder instead of letting React abort the entire tree. The
      // generated code gets a copy of React rather than a patched global:
      // an ES module namespace (and a frozen build) cannot be reassigned.
      const createElement = React.createElement;
      const CanvasReact = Object.assign({}, React, {
        createElement: function(type) {
          if (type === undefined || type === null) {
            return createElement('span', {
              title: 'Missing component',
              style: { display: 'inline-block', minWidth: 16, minHeight: 16, border: '1px dashed #f43f5e', borderRadius: 4 },
            });
          }
          return createElement.apply(this, arguments);
        },
      });
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
          if (name === 'react') return CanvasReact;
          if (name === 'react-dom' || name === 'react-dom/client') return ReactDOM;
          if (name === 'lucide-react') return LucideIcons;
          throw new Error('Unsupported canvas import: ' + name + '. Use a self-contained component.');
        };
        const evaluate = new Function('React', 'require',
          'const { useState, useEffect, useRef, useMemo, useCallback } = React;\\n' +
          'return function(module, exports) {\\n' +
          compiled + '\\n;' +
          'var __comp = module.exports.default || (typeof App !== "undefined" ? App : ' +
          '(typeof DefaultComponent !== "undefined" ? DefaultComponent : null));\\n' +
          'if (!__comp && module.exports) {\\n' +
          '  var __vals = Object.values(module.exports);\\n' +
          '  for (var i = 0; i < __vals.length; i++) {\\n' +
          '    if (typeof __vals[i] === "function") { __comp = __vals[i]; break; }\\n' +
          '  }\\n' +
          '}\\n' +
          'return __comp;\\n};');
        let Component = evaluate(CanvasReact, require)(module, module.exports);
        if (!Component) {
          const candidateNames = Array.from(${source}.matchAll(/(?:function|const|class)\\s+([A-Z]\\w*)/g), m => m[1]);
          for (const name of candidateNames) {
            if (name === 'App' || name === 'DefaultComponent' || name === 'React' || name === 'ReactDOM') continue;
            try {
              const findComp = new Function('React', 'require',
                'const { useState, useEffect, useRef, useMemo, useCallback } = React;\\n' +
                'return function(module, exports) {\\n' +
                compiled + '\\n;return typeof ' + name + ' !== "undefined" && typeof ' + name + ' === "function" ? ' + name + ' : null;\\n};');
              const found = findComp(CanvasReact, require)(module, module.exports);
              if (found) { Component = found; break; }
            } catch (_) {}
          }
        }
        if (!Component) throw new Error('No React component found (expected a default export or App).');
        const root = ReactDOM.createRoot(document.getElementById('root'));
        root.render(React.isValidElement(Component) ? Component : React.createElement(Component));
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
        <div role="alert" className="vsCanvasPreviewError" style={{ position: "absolute", top: 0, left: 0, width: "100%", boxSizing: "border-box", padding: "16px", background: "#fff1f2", color: "#9f1239", overflowWrap: "anywhere", zIndex: 10 }}>
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
