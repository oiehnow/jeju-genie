import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 로컬 개발: vite dev(5173) → FastAPI(8090) 프록시
// 배포: build 결과(dist)를 FastAPI가 정적 서빙하므로 프록시 불필요
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8090",
    },
  },
});
