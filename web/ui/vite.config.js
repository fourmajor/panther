import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  define: { "process.env.NODE_ENV": '"production"' },
  plugins: [tailwindcss(), {
    name: "panther-clean-generated-whitespace",
    generateBundle(_options, bundle) {
      for (const output of Object.values(bundle)) {
        if (output.type === "chunk") output.code = output.code.replace(/[ \t]+$/gm, "");
      }
    },
  }],
  build: {
    outDir: "../media-explorer", emptyOutDir: false, cssCodeSplit: false, minify: true,
    lib: { entry: "src/main.jsx", name: "PantherUI", formats: ["iife"], fileName: () => "ui-runtime.js", cssFileName: "ui-system" },
    rolldownOptions: { onwarn(warning, warn) { if (warning.code !== "MODULE_LEVEL_DIRECTIVE") warn(warning); } },
    sourcemap: false,
  },
});
