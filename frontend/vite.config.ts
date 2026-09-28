import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Dev-server-only proxy, so the app talks to its own origin in development exactly as it
    // does in production behind nginx. Without it the dev experience would need CORS and an
    // absolute URL, which is the habit that leads to a baked-in API base in the first place.
    proxy: {
      '/api': { target: process.env.DEV_BACKEND_URL ?? 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    css: false,
    coverage: { provider: 'v8', include: ['src/**'] },
  },
});
