/// <reference types="vitest/config" />
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

// In sviluppo (`npm run dev`) le chiamate all'API vanno al server Python locale.
export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
