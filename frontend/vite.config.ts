import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath } from "node:url";
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';

export default defineConfig(({ mode }) => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const env = loadEnv(mode, root, "");
  return {
    plugins: [vue(), {
      name: 'local-pdf-font-assets',
      generateBundle() {
        for (const folder of ['cmaps', 'standard_fonts']) {
          const directory = path.join(root, 'frontend', 'node_modules', 'pdfjs-dist', folder);
          for (const filename of readdirSync(directory)) {
            if (/\.(bcmap|pfb|ttf)$/.test(filename)) this.emitFile({
              type: 'asset', fileName: 'pdfjs/' + folder + '/' + filename,
              source: readFileSync(path.join(directory, filename)),
            });
          }
        }
      },
      configureServer(server) {
        server.middlewares.use('/pdfjs', (req, res, next) => {
          const match = /^\/(cmaps|standard_fonts)\/([\w.-]+\.(?:bcmap|pfb|ttf))$/.exec((req.url || '').split('?')[0]);
          if (!match) return next();
          try {
            res.setHeader('Content-Type', 'application/octet-stream');
            res.end(readFileSync(path.join(root, 'frontend', 'node_modules', 'pdfjs-dist', match[1], match[2])));
          } catch { next(); }
        });
      },
    }],
    build: { rollupOptions: { output: { manualChunks: { pdf: ['pdfjs-dist'], icons: ['lucide'], math: ['katex'] } } } },
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": { target: "http://127.0.0.1:" + (env.PORT || "8080") },
        "/legacy": { target: "http://127.0.0.1:" + (env.PORT || "8080") }
      }
    }
  };
});
