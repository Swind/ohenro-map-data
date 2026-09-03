import { defineConfig } from "vite";
import { fileURLToPath, URL } from "node:url";
import { outputApiPlugin } from "./output-api-plugin";

export default defineConfig({
  plugins: [
    outputApiPlugin(fileURLToPath(new URL("../output", import.meta.url))),
  ],
  server: {
    port: 5173,
    host: "127.0.0.1",
  },
  build: {
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL("./index.html", import.meta.url)),
        editor: fileURLToPath(new URL("./editor.html", import.meta.url)),
      },
    },
  },
});
