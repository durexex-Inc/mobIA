import { resolve } from 'node:path'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
      // Ver `test/server-only-stub.ts`: o pacote real lanca fora do bundler do
      // Next, e sem este alias todo teste que toque `lib/servidor/` morre na
      // importacao.
      'server-only': resolve(__dirname, './test/server-only-stub.ts'),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    globals: true,
  },
})
