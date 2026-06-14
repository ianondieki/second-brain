#!/usr/bin/env node
/**
 * Regression test for the Morning Nudge workflow's logic.
 *
 *   node scripts/test-pipeline.mjs
 *
 * It loads n8n/morning-nudge-workflow.json and exercises the EXACT JavaScript
 * shipped in the Code nodes, plus the two HTTP request bodies, against a battery
 * of edge-case notes. No Docker, no API keys, no network — pure logic checks.
 * Exits non-zero on any failure (CI-friendly).
 *
 * What it cannot cover (needs the real stack): live image pulls, n8n's runtime
 * expression engine, and the live Groq/Evolution endpoints. Those are validated
 * by the §4 dry-run on the host.
 */
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const WF = path.join(HERE, '..', 'n8n', 'morning-nudge-workflow.json');

const wf = JSON.parse(fs.readFileSync(WF, 'utf8'));
const nodeNamed = (n) => wf.nodes.find((x) => x.name === n);
const codeOf = (n) => nodeNamed(n).parameters.jsCode;

// A hermetic temp vault so we never depend on the container path /data/vault.
const VAULT = fs.mkdtempSync(path.join(os.tmpdir(), 'sb-vault-'));
// Node 2 hardcodes the container path; rebind it to our temp dir for the test.
const scanCode = codeOf('Scan & Read Vault').replace("'/data/vault'", JSON.stringify(VAULT));
const filterCode = codeOf('Filter Stale Projects');
const groqBody = nodeNamed('Cloud LLM Synthesis (Groq)').parameters.jsonBody;
const evoBody = nodeNamed('Send to WhatsApp Gateway').parameters.jsonBody;

const runScan = () => new Function('require', scanCode)(require);
const runFilter = (items) => new Function('$input', filterCode)({ all: () => items });
// Emulate n8n's `={{ <expr> }}` evaluation for the HTTP body fields.
const evalExpr = (tpl, $json, $env) =>
  new Function('$json', '$env', 'return (' + tpl.replace(/^=\{\{/, '').replace(/\}\}$/, '').trim() + ');')($json, $env);

const reset = () => { fs.rmSync(VAULT, { recursive: true, force: true }); fs.mkdirSync(VAULT, { recursive: true }); };
const put = (rel, content) => {
  const p = path.join(VAULT, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content);
};

let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) { pass++; console.log('  ✓', msg); } else { fail++; console.log('  ✗ FAIL:', msg); } };

const env = { GROQ_API_KEY: 'gk', EVOLUTION_API_KEY: 'ek', EVOLUTION_INSTANCE: 'secondbrain', WA_TARGET_NUMBER: '2348012345678' };

// Dates RELATIVE to today (local), so this test never rots as the clock moves.
const D = (offsetDays) => {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const z = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
};

try {
  // ---------------------------------------------------------------- Round A
  console.log('\n# Round A — full edge-case vault: classify, parse, rank');
  reset();
  // deadline-bearing, 9 days stale, high priority
  put('projects/stripe.md', `---\ntype: project\ntitle: "Stripe billing migration"\nstatus: active\npriority: high\ndeadline: ${D(17)}\nlast_actionable_date: ${D(-9)}\nstale_after_days: 5\n---\n## Recent log\n- ${D(-9)} — Verified webhook signatures.\n`);
  // 1 day old -> not stale
  put('projects/warm.md', `---\ntype: project\ntitle: Warm\nstatus: active\npriority: high\nlast_actionable_date: ${D(-1)}\n---\n- still hot`);
  // blocked (not done), 25 days, medium, no deadline
  put('projects/blocked.md', `---\ntype: project\ntitle: Blocked thing\nstatus: blocked\npriority: medium\nlast_actionable_date: ${D(-25)}\n---\n- log stuck on vendor`);
  put('projects/done.md', `---\ntype: project\ntitle: Finished\nstatus: done\nlast_actionable_date: ${D(-300)}\n---`);
  put('learning/sr.md', `---\ntype: learning\ntitle: Spaced repetition\nlast_actionable_date: ${D(-300)}\n---`);
  // BOM + CRLF + quoted title + tags list; nearer deadline than stripe
  put('projects/bom.md', `﻿---\r\ntype: project\r\ntitle: "BOM note"\r\nstatus: active\r\npriority: high\r\ndeadline: ${D(6)}\r\nlast_actionable_date: ${D(-13)}\r\ntags: [a, b]\r\n---\r\n- next thing\r\n`);
  // inline # comments on values; low priority, no deadline
  put('projects/inline.md', `---\ntype: project   # a project\ntitle: Inline comments\nstatus: active  # working\npriority: low\nlast_actionable_date: ${D(-12)}\n---\n- next step`);
  // 10 days old but a 30-day threshold -> NOT stale
  put('projects/override.md', `---\ntype: project\ntitle: Slow burn\nstatus: active\npriority: high\nlast_actionable_date: ${D(-10)}\nstale_after_days: 30\n---\n- research`);
  // dormant, oldest, medium
  put('projects/dormant.md', `---\ntype: project\ntitle: Dormant\nstatus: dormant\npriority: medium\nlast_actionable_date: ${D(-74)}\n---\n- log old`);
  put('projects/nodate.md', '---\ntype: project\ntitle: No date\nstatus: active\n---\n- whatever');
  put('projects/plain.md', '# just a note\nno frontmatter here');
  put('projects/notes.txt', 'type: project');
  put('.obsidian/workspace.md', `---\ntype: project\nstatus: active\nlast_actionable_date: ${D(-2000)}\n---`);
  // deeply nested, 44 days, low priority -> tests recursion + tie-break
  put('projects/sub/deep/buried.md', `---\ntype: project\ntitle: Buried\nstatus: active\npriority: low\nlast_actionable_date: ${D(-44)}\n---\n- log deep`);

  // NOTE: staleness is relative to *today*; assert on membership/ordering, not
  // on absolute day counts, so this test stays correct as the clock advances.
  const items = runScan();
  ok(items.length === 12, 'Node2 scans 12 .md files (skips .txt and .obsidian/, recurses subfolders)');
  ok(!items.some((i) => i.json.file.endsWith('.txt')), 'Node2 ignores non-markdown');

  const out = runFilter(items);
  ok(out.length === 1, 'Node3 emits one aggregated item');
  const titles = JSON.parse(out[0].json.user).stale_projects.map((p) => p.title);
  ok(!titles.includes('Warm'), 'future-dated project excluded (not stale)');
  ok(!titles.includes('Finished'), 'done excluded');
  ok(!titles.includes('Spaced repetition'), 'learning excluded');
  ok(!titles.includes('Slow burn'), 'stale_after_days override respected');
  ok(!titles.includes('No date'), 'missing last_actionable_date excluded');
  ok(titles.includes('BOM note'), 'BOM+CRLF+quoted-title note parsed and flagged');
  ok(titles.includes('Inline comments'), 'inline # comments on values handled');
  ok(titles.includes('Buried'), 'deeply nested note discovered via recursion');
  // Ordering invariant: deadline-bearing first (asc by date), then by priority, then days_stale.
  const expected = ['BOM note', 'Stripe billing migration', 'Dormant', 'Blocked thing', 'Buried', 'Inline comments'];
  ok(JSON.stringify(titles) === JSON.stringify(expected), 'ranking = deadline(asc) > priority > days_stale  [' + titles.join(' > ') + ']');

  // ---------------------------------------------------------------- HTTP bodies
  console.log('\n# Round A — HTTP request bodies');
  const g = JSON.parse(JSON.stringify(evalExpr(groqBody, out[0].json, env)));
  ok(g.model === 'llama-3.3-70b-versatile', 'Groq body: model set');
  ok(g.messages[0].role === 'system' && g.messages[0].content === out[0].json.system, 'Groq body: system message intact');
  ok(g.messages[1].role === 'user' && g.messages[1].content === out[0].json.user, 'Groq body: user JSON intact through escaping');
  const mock = { choices: [{ message: { content: '🧊 *HOOK*\nYour _BOM note_ went cold.' } }] };
  const e = JSON.parse(JSON.stringify(evalExpr(evoBody, mock, env)));
  ok(e.number === '2348012345678', 'Evolution body: number from $env');
  ok(e.text === mock.choices[0].message.content, 'Evolution body: text = LLM content');
  ok(e.delay === 1200, 'Evolution body: typing delay set');

  // ---------------------------------------------------------------- Round B
  console.log('\n# Round B — nothing stale halts the pipeline');
  reset();
  put('p/warm.md', `---\ntype: project\ntitle: W\nstatus: active\nlast_actionable_date: ${D(-1)}\n---\n- fresh`);
  put('p/done.md', `---\ntype: project\ntitle: D\nstatus: done\nlast_actionable_date: ${D(-300)}\n---`);
  ok(runFilter(runScan()).length === 0, 'Node3 returns [] so nodes 4 & 5 never run');

  // ---------------------------------------------------------------- Round C
  console.log('\n# Round C — empty vault raises an actionable error');
  reset();
  let threw = false, msg = '';
  try { runScan(); } catch (err) { threw = true; msg = err.message; }
  ok(threw && /VAULT_PATH/.test(msg), 'Node2 throws a helpful error when the vault is empty');

  // ---------------------------------------------------------------- Round D
  console.log('\n# Round D — note with no signal lines yields empty recent_notes');
  reset();
  put('p/bare.md', `---\ntype: project\ntitle: Bare\nstatus: active\npriority: high\nlast_actionable_date: ${D(-100)}\n---\nJust prose, nothing structured.`);
  ok(JSON.parse(runFilter(runScan())[0].json.user).stale_projects[0].recent_notes === '', 'empty recent_notes when no list/date/next lines (prompt has a fallback)');

} finally {
  fs.rmSync(VAULT, { recursive: true, force: true });
}

console.log(`\n==== ${pass} passed, ${fail} failed ====`);
process.exit(fail ? 1 : 0);
