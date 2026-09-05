import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

// Exercise the production alignment code without Next or a network request.
const source = fs.readFileSync(new URL('../src/lib/benchmark.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const { alignBenchmark, fetchSpyBenchmarkSeries } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const closes = [
  { as_of: '2026-09-01T21:00:00Z', close: 100 },
  { as_of: '2026-09-02T21:00:00Z', close: 110 },
  { as_of: '2026-09-03T21:00:00Z', close: 500 },
];
const start = '2026-09-02T16:00:00Z';
const end = '2026-09-03T15:00:00Z';
const aligned = alignBenchmark(closes, start, end);
assert.equal(aligned[0].value, 100);
assert.equal(aligned[0].nav, 100); // never tomorrow's close as inception price
assert.equal(aligned.length, 2);
assert.ok(Math.abs(aligned[1].value - 110) < 1e-10);
assert.ok(aligned.every(row => Date.parse(row.as_of) <= Date.parse(end)));
assert.equal(alignBenchmark(closes.slice(1), start, end), null);
assert.equal(alignBenchmark(closes, 'bad', end), null);
assert.equal(alignBenchmark(closes, end, start), null);
assert.equal(alignBenchmark([{ as_of: closes[0].as_of, close: NaN }], start, end), null);

// Provider bar timestamps are session opens; a daily close is unavailable then.
const originalFetch = globalThis.fetch;
globalThis.fetch = async () => ({ ok: true, json: async () => ({ chart: { result: [{
  timestamp: [Date.parse('2026-09-01T13:30:00Z') / 1000, Date.parse('2026-09-02T13:30:00Z') / 1000],
  indicators: { quote: [{ close: [100, 999] }] },
}] } }) });
const intraday = await fetchSpyBenchmarkSeries('2026-09-02T14:00:00Z', '2026-09-02T15:00:00Z');
assert.equal(intraday.length, 1);
assert.equal(intraday[0].nav, 100);
globalThis.fetch = originalFetch;
console.log('Benchmark alignment and daily-bar availability checks passed.');
