/**
 * Package the built dashboard into a single self-contained HTML file.
 *
 * Inlines the CSS, the JS bundle and the exported API snapshot, so the result
 * runs with no backend and no same-origin asset requests - which is what a
 * shared read-only deployment needs.
 *
 *   node scripts/package-static.mjs [outfile]
 */

import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const dist = join(root, 'dist', 'assets');
const out = process.argv[2] ?? join(root, 'atmosguard-static.html');

const files = readdirSync(dist);
const css = files.find((f) => f.endsWith('.css'));
const js = files.find((f) => f.endsWith('.js'));
if (!css || !js) throw new Error('build assets not found - run `npm run build` first');

const snapshot = readFileSync(join(root, 'snapshot.json'), 'utf8');

// The snapshot is embedded as a JSON string parsed at runtime rather than as
// an object literal: it parses considerably faster at this size, and it cannot
// be reinterpreted as JavaScript.
const encoded = JSON.stringify(snapshot);

// A literal `</script` inside any embedded text would close the tag early.
const safe = (text) => text.replaceAll('</script', '<\\/script');

// The charset declaration has to come first and has to be present: served
// from a file:// URL or any host that does not set a charset header, the
// browser falls back to latin-1 and every em dash in the UI turns to mojibake.
const html = `<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AtmosGuard</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" media="print" onload="this.media='all'">
<style>
${readFileSync(join(dist, css), 'utf8')}
</style>
<div id="root"></div>
<script>window.__ATMOSGUARD_SNAPSHOT__ = JSON.parse(${safe(encoded)});</script>
<script type="module">
${safe(readFileSync(join(dist, js), 'utf8'))}
</script>
`;

writeFileSync(out, html);
console.log(`${out}  ${(html.length / 1_048_576).toFixed(1)} MB`);
