import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// In development, /api requests are forwarded to the FastAPI backend.
export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: { '/api': `http://localhost:${process.env.API_PORT ?? 8010}` },
  },
})
