import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "0.0.0.0", // 允许局域网访问
    port: 8081, // 指定前端端口
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000", // 后端 API 地址
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""), // 如果后端路径不需要 /api 前缀可开启
      },
    },
  },
});
