import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const packageJsonPath = resolve(__dirname, "package.json");
const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf-8")) as {
  version?: string;
};
const appVersion = String(process.env.VITE_APP_VERSION || packageJson.version || "N/A");

// "desktop" = installer build talking to its bundled local backend.
// "hosted" = served by the operator's shared server (paid voice coach only).
// Both ignore local .env files so no developer token leaks into a bundle.
const isolatedModes = new Set(["desktop", "hosted"]);

export default defineConfig(({ mode }) => ({
  envDir: isolatedModes.has(mode) ? false : undefined,
  envPrefix: isolatedModes.has(mode) ? [] : "VITE_",
  plugins: [react()],
  base: "./",
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
    // Installer builds always target their own backend and never embed a
    // developer's .env.local API tokens in distributable JavaScript.
    ...(mode === "desktop" ? {
      "import.meta.env.VITE_API_URL": JSON.stringify("http://127.0.0.1:8000"),
      "import.meta.env.VITE_API_TOKEN": JSON.stringify(""),
      "import.meta.env.VITE_API_ADMIN_TOKEN": JSON.stringify("")
    } : {}),
    ...(mode === "hosted" ? {
      "import.meta.env.VITE_HOSTED": JSON.stringify("true"),
      "import.meta.env.VITE_API_URL": JSON.stringify(""),
      "import.meta.env.VITE_API_TOKEN": JSON.stringify(""),
      "import.meta.env.VITE_API_ADMIN_TOKEN": JSON.stringify("")
    } : {})
  },
  build: {
    target: "es2022",
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/react-dom") || id.includes("node_modules/react/") || id.includes("node_modules/scheduler")) {
            return "framework";
          }
          if (id.includes("node_modules/lucide-react")) {
            return "icons";
          }
        }
      }
    }
  },
  server: {
    port: 5173,
    host: "127.0.0.1"
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts"
  }
}));
