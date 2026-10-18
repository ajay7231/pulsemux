import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const directory = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../worker-py/web/dashboard",
);
const manifest = JSON.parse(
  readFileSync(resolve(directory, ".vite/manifest.json"), "utf8"),
);
const files = new Set();
function collect(key) {
  const chunk = manifest[key];
  if (files.has(chunk.file)) return;
  files.add(chunk.file);
  for (const css of chunk.css || []) files.add(css);
  for (const imported of chunk.imports || []) collect(imported);
}
for (const [key, chunk] of Object.entries(manifest))
  if (chunk.isEntry) collect(key);
const bytes = [...files].reduce(
  (sum, file) => sum + gzipSync(readFileSync(resolve(directory, file))).length,
  0,
);
const limit = 220 * 1024;
console.log(
  `Initial dashboard assets: ${(bytes / 1024).toFixed(1)} KiB gzip / ${limit / 1024} KiB budget`,
);
if (bytes > limit) {
  console.error(
    "Initial bundle exceeds the budget. Keep feature code lazy and review new dependencies.",
  );
  process.exitCode = 1;
}
