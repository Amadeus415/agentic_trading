import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import ts from 'typescript';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'edgecraft-report-test-'));
const priorDb = process.env.EDGECRAFT_TEST_DB;
const priorReport = process.env.EDGECRAFT_FUND_REPORT;
process.env.EDGECRAFT_TEST_DB = path.join(directory, 'fund.db');
delete process.env.EDGECRAFT_FUND_REPORT;
try {
  const dbStub = `data:text/javascript;base64,${Buffer.from('export function resolveFundDbPath() { return process.env.EDGECRAFT_TEST_DB; }').toString('base64')}`;
  const source = fs.readFileSync(new URL('../src/lib/report.ts', import.meta.url), 'utf8').replace('"./db"', JSON.stringify(dbStub));
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
  const { readFundReport } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
  fs.writeFileSync(path.join(directory, 'fund-report.json'), JSON.stringify({ fund_id: 'v2', summary: { closed_trades: 0 } }));
  assert.equal(readFundReport('v1'), null);
  assert.equal(readFundReport('v2').fund_id, 'v2');
  const archive = path.join(directory, 'fund-report-v1.json');
  fs.writeFileSync(archive, JSON.stringify({ fund_id: 'v1', summary: { closed_trades: 22 } }));
  assert.equal(readFundReport('v1').summary.closed_trades, 22);
  process.env.EDGECRAFT_FUND_REPORT = archive;
  assert.equal(readFundReport('v2'), null);
  assert.equal(readFundReport('v1').fund_id, 'v1');
  console.log('Report selection never substitutes another fund, including explicit overrides.');
} finally {
  if (priorDb === undefined) delete process.env.EDGECRAFT_TEST_DB; else process.env.EDGECRAFT_TEST_DB = priorDb;
  if (priorReport === undefined) delete process.env.EDGECRAFT_FUND_REPORT; else process.env.EDGECRAFT_FUND_REPORT = priorReport;
  fs.rmSync(directory, { recursive: true, force: true });
}
