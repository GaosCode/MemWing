import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { memwingMockApiPlugin } from "./vite.mock-api";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_MEMWING_");
  const proxyTarget = env.VITE_MEMWING_API_PROXY_TARGET || process.env.VITE_MEMWING_API_PROXY_TARGET;
  const mockFlag = env.VITE_MEMWING_USE_MOCK_API || process.env.VITE_MEMWING_USE_MOCK_API;
  const useMockApi = mockFlag === "1";

  return {
    plugins: [
      react(),
      ...(useMockApi ? [memwingMockApiPlugin()] : []),
    ],
    server: {
      proxy: useMockApi
        ? undefined
        : {
            "/v1": {
              target: proxyTarget ?? "http://127.0.0.1:8000",
              changeOrigin: true,
            },
          },
    },
  };
});
