/**
 * Prove the static build shows exactly what the live API would.
 *
 *   node scripts/check-sidecar-parity.mjs <api-dump.json> <compiled stationSidecar.js>
 *
 * The dump is written by `backend/scripts/check_sidecar_parity.py`, which also
 * compiles the TypeScript and runs this. Every payload in it is rebuilt from
 * the station's sidecar file and compared field by field - numbers with ===,
 * not "close enough". One mismatch fails the run.
 */
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [dumpPath, modulePath] = process.argv.slice(2);
const { rebuildReplay } = await import(pathToFileURL(path.resolve(modulePath)).href);
const dump = JSON.parse(fs.readFileSync(dumpPath, 'utf8'));
const sidecarDir = path.join(path.dirname(new URL(import.meta.url).pathname), '..', 'sidecar');

function diff(a, b, where) {
  if (typeof a === 'number' && typeof b === 'number') return a === b ? [] : [`${where}: api=${a} static=${b}`];
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') {
    return a === b ? [] : [`${where}: api=${JSON.stringify(a)} static=${JSON.stringify(b)}`];
  }
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].flatMap((k) => diff(a[k], b[k], `${where}.${k}`));
}

const cache = new Map();
let checked = 0;
let failed = 0;
for (const [key, payload] of Object.entries(dump)) {
  const [station, day] = key.split('|');
  if (!cache.has(station)) {
    cache.set(station, JSON.parse(fs.readFileSync(path.join(sidecarDir, `station-${station}.json`), 'utf8')));
  }
  const problems = diff(payload, rebuildReplay(cache.get(station), day), key);
  checked += 1;
  if (problems.length) {
    failed += 1;
    if (failed <= 5) console.error(problems.slice(0, 8).join('\n'));
  }
}
console.log(`parity: ${checked} replays across ${cache.size} stations, ${failed} mismatched`);
process.exit(failed ? 1 : 0);
