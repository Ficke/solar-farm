import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// `bun run dev` proxies /api to a local server with made-up readings:
//   uv run uvicorn solar_server.dev:app --port 8000
export default defineConfig({
  plugins: [svelte()],
  server: { proxy: { "/api": "http://localhost:8000" } },
});
