// Minimal Vite config. The app is a single page (index.html in this dir) — no SPA routing.
// `npm run dev` serves on :5173; `npm run build` outputs to `web/dist/` ready for static hosting.
export default {
  root: ".",
  base: "./",
  server: { port: 5173, strictPort: false, open: false },
  build: { outDir: "dist", sourcemap: true, target: "es2020" },
};
