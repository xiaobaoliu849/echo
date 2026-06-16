import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
const packageJsonPath = resolve(__dirname, "package.json");
const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf-8"));
const appVersion = String(process.env.VITE_APP_VERSION || packageJson.version || "N/A");
export default defineConfig({
    plugins: [react()],
    base: "./",
    define: {
        __APP_VERSION__: JSON.stringify(appVersion)
    },
    resolve: {
        alias: {
            "@lobehub/ui/icons": resolve(__dirname, "src/test/mockLobeUi.ts"),
            "@lobehub/ui": resolve(__dirname, "src/test/mockLobeUi.ts"),
            "antd": resolve(__dirname, "src/test/mockLobeUi.ts")
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
});
