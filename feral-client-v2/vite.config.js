import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// feral-client-v2 is served at / by default (v2 is the only UI). The /v2/
// alias is retained for back-compat. Relative asset base works at both
// mount points because Vite emits "./assets/..." refs.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
