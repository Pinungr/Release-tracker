import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // `npm run build` writes ./dist, which the FastAPI process serves as the web
  // UI — the app ships as one deployable, not as a separate static site.
  build: { outDir: 'dist', emptyOutDir: true },

  // The dev server exists only for hot reloading while editing React code. It
  // proxies /api to the application so the browser still talks to a single
  // origin and the same relative URLs work in both modes.
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
