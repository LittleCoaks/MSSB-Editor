import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// Builds into the Python package so the server (and PyInstaller) ship it.
export default defineConfig({
  plugins: [svelte()],
  base: './',
  build: { outDir: '../zzzzdat/ui/dist', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8420', '/legacy': 'http://127.0.0.1:8420', '/vendor': 'http://127.0.0.1:8420' } },
})
