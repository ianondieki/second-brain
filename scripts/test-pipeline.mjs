#!/usr/bin/env node
/**
 * Regression test for the Second Brain workflows' logic.
 *
 *   node scripts/test-pipeline.mjs
 *
 * Loads the three workflow JSON files and exercises the EXACT JavaScript shipped
 * in their Code nodes (plus the HTTP request-body expressions) against a battery
 * of edge-case fixtures. No Docker, no API keys, no network — pure logic checks.
 * Exits non-zero on any failure (CI-friendly).
 *
 * Container paths inside the shipped code ('/data/vault', '/data/inbox', the
 * actions log) are rebound to hermetic temp dirs so the test runs anywhere.
 * All fixture dates are relative to "today", so the test never rots.
 *
 * Not covered (needs the real stack): live image pulls, n8n's runtime expression
 * engine, the live Groq/Telegram endpoints, and Telegram's getUpdates polling.
 */
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const N8N = path.join(HERE, '..', 'n8n');
const load = (f) => JSON.parse(fs.readFileSync(path.join(N8N, f), 'utf8'));

const errwf = load('error-handler-workflow.json');
const telegram = load('morning-nudge-telegram.json');
const tgAssistant = load('telegram-assistant-workflow.json');
const nodeNamed = (wf, n) => wf.nodes.find((x) => x.name === n);
const codeOf = (wf, n) => nodeNamed(wf, n).parameters.jsCode;

// Hermetic temp dirs standing in for the container mounts.
const VAULT = fs.mkdtempSync(path.join(os.tmpdir(), 'sb-vault-'));
const INBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'sb-inbox-'));
const ACTIONS = path.join(INBOX, '.actions.jsonl');

// Rebind hardcoded container paths to the temp dirs, then compile the shipped code.
// Telegram is the sole delivery channel; the morning pipeline lives in its workflow.
const scanCode = codeOf(telegram, 'Scan & Read Vault').replace("'/data/vault'", JSON.stringify(VAULT));
const filterCode = codeOf(telegram, 'Filter Stale Projects')
  .replace("'/data/inbox/.actions.jsonl'", JSON.stringify(ACTIONS))
  .replace("'/data/inbox/.tg_context.json'", JSON.stringify(path.join(INBOX, '.tg_context.json')));
const errorCode = codeOf(errwf, 'Format Alert');
const extractCode = codeOf(telegram, 'Extract Nudge');
const extractTgCode = extractCode;            // same node — the nudge renders HTML inline
const groqBody = nodeNamed(telegram, 'Cloud LLM Synthesis (Groq)').parameters.jsonBody;
const tgBody = nodeNamed(telegram, 'Send to Telegram').parameters.jsonBody;
const filterTgCode = filterCode;              // the nudge filter also writes the focus file

// Two-way Telegram assistant — polling getUpdates, owner-only, commands + chat.
const routeCode = codeOf(tgAssistant, 'Route & Handle').replace("'/data/inbox'", JSON.stringify(INBOX));
const readOffsetCode = codeOf(tgAssistant, 'Read Offset').replace("'/data/inbox/.tg_offset'", JSON.stringify(path.join(INBOX, '.tg_offset')));
const extractReplyCode = codeOf(tgAssistant, 'Extract Reply').replace("'/data/inbox/.tg_history.json'", JSON.stringify(path.join(INBOX, '.tg_history.json')));
const tgSendBody = nodeNamed(tgAssistant, 'Send Reply').parameters.jsonBody;
const tgGetUrl = nodeNamed(tgAssistant, 'Get Updates').parameters.url;

const runScan = () => new Function('require', scanCode)(require);
const runFilter = (items) => new Function('$input', 'require', filterCode)({ all: () => items }, require);
const runError = (item) => new Function('$input', errorCode)({ first: () => item });
const runExtract = (json) => new Function('$input', extractCode)({ first: () => ({ json }) });
const runExtractTg = (json) => new Function('$input', extractTgCode)({ first: () => ({ json }) });
const tgEnv = { TELEGRAM_CHAT_ID: '6379545167' };
const runRoute = (result) => new Function('$input', 'require', '$env', routeCode)({ first: () => ({ json: { result } }) }, require, tgEnv);
const runReadOffset = () => new Function('require', readOffsetCode)(require);
const runFilterTg = (items) => new Function('$input', 'require', filterTgCode)({ all: () => items }, require);
const runExtractReply = (json) => new Function('$input', 'require', extractReplyCode)({ first: () => ({ json }) }, require);
const tgMsg = (id, text, over = {}) => ({ update_id: id, message: { message_id: id, from: { id: 6379545167, is_bot: false }, chat: { id: 6379545167, type: 'private' }, text, ...over } });
const evalExpr = (tpl, $json, $env) =>
  new Function('$json', '$env', 'return (' + tpl.replace(/^=\{\{/, '').replace(/\}\}$/, '').trim() + ');')($json, $env);

const reset = () => {
  fs.rmSync(VAULT, { recursive: true, force: true }); fs.mkdirSync(VAULT, { recursive: true });
  fs.rmSync(INBOX, { recursive: true, force: true }); fs.mkdirSync(INBOX, { recursive: true });
};
const put = (rel, content) => {
  const p = path.join(VAULT, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content);
};
const writeActions = (records) => fs.writeFileSync(ACTIONS, records.map((r) => JSON.stringify(r)).join('\n') + '\n');

let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) { pass++; console.log('  ✓', msg); } else { fail++; console.log('  ✗ FAIL:', msg); } };

const env = { GROQ_API_KEY: 'gk' };

// Dates RELATIVE to today (local), so this test never rots as the clock moves.
const D = (offsetDays) => {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const z = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
};
const wstale = (title) => {
  const o = runFilter(runScan());
  return o.length > 0 && JSON.parse(o[0].json.user).stale_projects.some((p) => p.title === title);
};

try {
  // ---------------------------------------------------------------- Round A
  console.log('\n# Round A — classify, parse, rank');
  reset();
  put('projects/stripe.md', `---\ntype: project\ntitle: "Stripe billing migration"\nstatus: active\npriority: high\ndeadline: ${D(17)}\nlast_actionable_date: ${D(-9)}\nstale_after_days: 5\n---\n## Recent log\n- ${D(-9)} — Verified webhook signatures.\n`);
  put('projects/warm.md', `---\ntype: project\ntitle: Warm\nstatus: active\npriority: high\nlast_actionable_date: ${D(-1)}\n---\n- still hot`);
  put('projects/blocked.md', `---\ntype: project\ntitle: Blocked thing\nstatus: blocked\npriority: medium\nlast_actionable_date: ${D(-25)}\n---\n- log stuck on vendor`);
  put('projects/done.md', `---\ntype: project\ntitle: Finished\nstatus: done\nlast_actionable_date: ${D(-300)}\n---`);
  put('learning/sr.md', `---\ntype: learning\ntitle: Spaced repetition\nlast_actionable_date: ${D(-300)}\n---`);
  put('projects/bom.md', `﻿---\r\ntype: project\r\ntitle: "BOM note"\r\nstatus: active\r\npriority: high\r\ndeadline: ${D(6)}\r\nlast_actionable_date: ${D(-13)}\r\ntags: [a, b]\r\n---\r\n- next thing\r\n`);
  put('projects/inline.md', `---\ntype: project   # a project\ntitle: Inline comments\nstatus: active  # working\npriority: low\nlast_actionable_date: ${D(-12)}\n---\n- next step`);
  put('projects/override.md', `---\ntype: project\ntitle: Slow burn\nstatus: active\npriority: high\nlast_actionable_date: ${D(-10)}\nstale_after_days: 30\n---\n- research`);
  put('projects/dormant.md', `---\ntype: project\ntitle: Dormant\nstatus: dormant\npriority: medium\nlast_actionable_date: ${D(-74)}\n---\n- log old`);
  put('projects/nodate.md', '---\ntype: project\ntitle: No date\nstatus: active\n---\n- whatever');
  put('projects/plain.md', '# just a note\nno frontmatter here');
  put('projects/notes.txt', 'type: project');
  put('.obsidian/workspace.md', `---\ntype: project\nstatus: active\nlast_actionable_date: ${D(-2000)}\n---`);
  put('projects/sub/deep/buried.md', `---\ntype: project\ntitle: Buried\nstatus: active\npriority: low\nlast_actionable_date: ${D(-44)}\n---\n- log deep`);

  const items = runScan();
  ok(items.length === 12, 'Node2 scans 12 .md files (skips .txt and .obsidian/, recurses subfolders)');
  const out = runFilter(items);
  ok(out.length === 1, 'Node3 emits one aggregated item');
  const titles = JSON.parse(out[0].json.user).stale_projects.map((p) => p.title);
  ok(!titles.includes('Warm') && !titles.includes('Finished') && !titles.includes('Spaced repetition'), 'warm/done/learning excluded');
  ok(!titles.includes('Slow burn') && !titles.includes('No date'), 'stale_after_days override + missing-date excluded');
  ok(titles.includes('BOM note') && titles.includes('Inline comments') && titles.includes('Buried'), 'BOM/CRLF, inline comments, deep recursion all handled');
  const expected = ['BOM note', 'Stripe billing migration', 'Dormant', 'Blocked thing', 'Buried', 'Inline comments'];
  ok(JSON.stringify(titles) === JSON.stringify(expected), 'ranking = deadline(asc) > priority > days_stale  [' + titles.join(' > ') + ']');

  // HTTP bodies
  const g = JSON.parse(JSON.stringify(evalExpr(groqBody, out[0].json, env)));
  ok(g.model === 'llama-3.3-70b-versatile' && g.messages[0].content === out[0].json.system && g.messages[1].content === out[0].json.user, 'Groq body intact (default model + messages + escaping)');
  const gCustom = JSON.parse(JSON.stringify(evalExpr(groqBody, out[0].json, { ...env, GROQ_MODEL: 'llama-3.1-8b-instant' })));
  ok(gCustom.model === 'llama-3.1-8b-instant', 'GROQ_MODEL env overrides the default model');
  const reviewsA = JSON.parse(out[0].json.user).due_reviews.map((r) => r.topic);
  ok(reviewsA.includes('Spaced repetition'), 'overdue learning log surfaced in due_reviews');
  const stripeRec = JSON.parse(out[0].json.user).stale_projects.find((p) => p.title === 'Stripe billing migration').recent_notes;
  ok(!/Recent log/.test(stripeRec) && /Verified/.test(stripeRec), 'recent_notes excludes Markdown headings, keeps log lines');

  // ---------------------------------------------------------------- Round B/C/D
  console.log('\n# Round B/C/D — halt, empty vault, empty recent_notes');
  reset();
  put('p/warm.md', `---\ntype: project\ntitle: W\nstatus: active\nlast_actionable_date: ${D(-1)}\n---\n- fresh`);
  put('p/done.md', `---\ntype: project\ntitle: D\nstatus: done\nlast_actionable_date: ${D(-300)}\n---`);
  ok(runFilter(runScan()).length === 0, 'nothing stale -> Node3 returns [] (nodes 4 & 5 never run)');
  reset();
  let threw = false, m2 = '';
  try { runScan(); } catch (err) { threw = true; m2 = err.message; }
  ok(threw && /VAULT_PATH/.test(m2), 'empty vault -> Node2 throws an actionable error');
  reset();
  put('p/bare.md', `---\ntype: project\ntitle: Bare\nstatus: active\npriority: high\nlast_actionable_date: ${D(-100)}\n---\nJust prose, nothing structured.`);
  ok(JSON.parse(runFilter(runScan())[0].json.user).stale_projects[0].recent_notes === '', 'empty recent_notes when no signal lines');

  // ---------------------------------------------------------------- Round E (NEW)
  console.log('\n# Round E — action-log overrides (touch / done / stale)');
  reset();
  put('projects/stripe.md', `---\ntype: project\ntitle: "Stripe billing migration"\nstatus: active\npriority: high\nlast_actionable_date: ${D(-9)}\n---\n- log`);
  ok(wstale('Stripe billing migration'), 'baseline: Stripe is stale with no actions');
  writeActions([{ ts: new Date().toISOString().replace(/T.*/, 'T09:00:00Z'), action: 'touch', project: 'stripe' }]);
  ok(!wstale('Stripe billing migration'), '/touch today resets the clock -> no longer stale (substring match)');
  writeActions([{ ts: D(-30) + 'T09:00:00Z', action: 'touch', project: 'stripe' }]);
  ok(wstale('Stripe billing migration'), 'an OLD /touch (30d ago) does not rescue it');
  writeActions([{ ts: new Date().toISOString(), action: 'done', project: 'Stripe billing migration' }]);
  ok(!wstale('Stripe billing migration'), '/done removes it from nudges entirely');
  writeActions([
    { ts: D(-30) + 'T09:00:00Z', action: 'done', project: 'stripe' },
    { ts: new Date().toISOString(), action: 'reopen', project: 'stripe' },
  ]);
  ok(wstale('Stripe billing migration'), 'latest action wins: /reopen after an old /done brings it back');

  // ---------------------------------------------------------------- Round G (NEW)
  console.log('\n# Round G — error-handler formatting (Telegram HTML)');
  const alert = runError({ json: { workflow: { name: 'Autonomous Morning Nudge Pipeline (Telegram)' }, execution: { lastNodeExecuted: 'Cloud LLM Synthesis (Groq)', error: { message: 'Request failed with status code 401 <x>' }, url: 'http://localhost:5678/execution/42' } } });
  const at = alert[0].json.text;
  ok(/Second Brain failed/.test(at) && /Morning Nudge/.test(at) && /401/.test(at) && /execution\/42/.test(at), 'error alert includes workflow, node, message, url');
  ok(/<b>Workflow:<\/b>/.test(at) && /401 &lt;x&gt;/.test(at), 'error alert renders Telegram HTML and escapes < > in the message');
  const alert2 = runError({ json: {} });
  ok(/unknown workflow/.test(alert2[0].json.text), 'error formatter is defensive against a sparse payload');

  // ---------------------------------------------------------------- Round H (NEW)
  console.log('\n# Round H — learning-log spaced reviews');
  const wreviews = () => { const o = runFilter(runScan()); return o.length ? JSON.parse(o[0].json.user).due_reviews.map((r) => r.topic) : []; };
  reset();
  put('learning/due.md', `---\ntype: learning\ntitle: Due topic\nlast_actionable_date: ${D(-10)}\n---\n- notes`);
  put('learning/fresh.md', `---\ntype: learning\ntitle: Fresh topic\nlast_actionable_date: ${D(-2)}\n---`);
  put('learning/custom.md', `---\ntype: learning\ntitle: Custom interval\nreview_interval_days: 3\nlast_actionable_date: ${D(-5)}\nconfidence: 0.2\n---`);
  put('learning/finished.md', `---\ntype: learning\ntitle: Mastered\nstatus: done\nlast_actionable_date: ${D(-99)}\n---`);
  let revs = wreviews();
  ok(revs.includes('Due topic'), 'learning note past the default 7d interval is due');
  ok(!revs.includes('Fresh topic'), 'recently-reviewed learning note is not due');
  ok(revs.includes('Custom interval'), 'review_interval_days override honoured');
  ok(!revs.includes('Mastered'), 'status:done learning note excluded from reviews');
  const oH = runFilter(runScan());
  const pj = JSON.parse(oH[0].json.user);
  ok(oH.length === 1 && pj.stale_projects.length === 0 && pj.due_reviews.length > 0, 'review-only morning (no stale projects) still emits a message');
  writeActions([{ ts: new Date().toISOString(), action: 'done', project: 'Due topic' }]);
  ok(!wreviews().includes('Due topic'), '/done on a learning topic stops its reviews too');
  reset();
  put('learning/a.md', `---\ntype: learning\ntitle: A\nlast_actionable_date: ${D(-20)}\n---`);
  put('learning/b.md', `---\ntype: learning\ntitle: B\nlast_actionable_date: ${D(-40)}\n---`);
  ok(JSON.stringify(wreviews()) === JSON.stringify(['B', 'A']), 'reviews sorted most-overdue first');

  // ---------------------------------------------------------------- Round I (NEW)
  console.log('\n# Round I — LLM response normalization & guard (Extract Nudge)');
  ok(runExtract({ choices: [{ message: { content: '  🧊 *HOOK*\nGo  ' } }] })[0].json.text === '🧊 *HOOK*\nGo',
    'Groq/OpenAI shape -> trimmed text');
  ok(runExtract({ candidates: [{ content: { parts: [{ text: '🧊 ' }, { text: 'HOOK' }] } }] })[0].json.text === '🧊 HOOK',
    'Gemini shape (candidates/parts) -> concatenated text');
  ok(runExtract({ choices: [{ message: { content: '```\n🧊 *HOOK*\nx\n```' } }] })[0].json.text === '🧊 *HOOK*\nx',
    'stray ``` code fences are unwrapped');
  let xThrew = false, xMsg = '';
  try { runExtract({ choices: [{ message: { content: '   ' }, finish_reason: 'content_filter' }] }); }
  catch (err) { xThrew = true; xMsg = err.message; }
  ok(xThrew && /no usable text/.test(xMsg), 'empty completion throws (no blank Telegram send)');
  ok(/content_filter/.test(xMsg), 'thrown error surfaces the finish_reason for triage');
  let eThrew = false, eMsg = '';
  try { runExtract({ error: { message: 'rate_limit_exceeded' } }); }
  catch (err) { eThrew = true; eMsg = err.message; }
  ok(eThrew && /rate_limit_exceeded/.test(eMsg), 'error-shaped 200 surfaces the provider message, not a TypeError');
  const longOut = runExtract({ choices: [{ message: { content: 'x'.repeat(5000) } }] })[0].json.text;
  ok(longOut.length <= 4000 && longOut.endsWith('…'), 'runaway output is truncated with an ellipsis');

  // ---------------------------------------------------------------- Round J (NEW)
  console.log('\n# Round J — Telegram HTML rendering (Extract Nudge + send body, Telegram variant)');
  const tg = runExtractTg({ choices: [{ message: { content: '🧊 *HOOK*\n_soft_ <x> & y' } }] })[0].json;
  ok(tg.text === '🧊 *HOOK*\n_soft_ <x> & y', 'telegram: raw .text is preserved untouched');
  ok(tg.html === '🧊 <b>HOOK</b>\n<i>soft</i> &lt;x&gt; &amp; y',
    'telegram: *bold*/_italic_ -> <b>/<i>, and <,>,& escaped FIRST so nothing breaks parsing');
  ok(runExtractTg({ choices: [{ message: { content: 'a * b' } }] })[0].json.html === 'a * b',
    'telegram: a lone asterisk is left literal (no dangling <b>)');
  const tgB = evalExpr(tgBody, { html: '<b>HOOK</b>' }, { TELEGRAM_CHAT_ID: '6379545167' });
  ok(tgB.chat_id === '6379545167' && tgB.text === '<b>HOOK</b>', 'telegram body: chat_id from $env, text from $json.html');
  ok(tgB.parse_mode === 'HTML', 'telegram body: parse_mode HTML so the tags render');

  // ---------------------------------------------------------------- Round K (NEW)
  console.log('\n# Round K — Telegram two-way assistant (poll, route, commands, chat)');
  reset();

  // Read Offset: missing state file -> 0; existing -> parsed.
  ok(runReadOffset()[0].json.offset === 0, 'read offset: no state file -> 0');
  fs.writeFileSync(path.join(INBOX, '.tg_offset'), '4242');
  ok(runReadOffset()[0].json.offset === 4242, 'read offset: existing state file is parsed');
  reset();

  // Guards: owner-only, no self-loop, non-text ignored.
  ok(runRoute([{ update_id: 1, message: { from: { id: 999, is_bot: false }, chat: { id: 999, type: 'private' }, text: 'hi' } }]).length === 0,
    'route: stranger chat is ignored (owner-only, no surprise LLM bill)');
  ok(runRoute([tgMsg(2, 'hi', { from: { id: 6379545167, is_bot: true } })]).length === 0,
    'route: bot-authored message ignored (no self-loop)');
  ok(runRoute([{ update_id: 3, message: { from: { id: 6379545167, is_bot: false }, chat: { id: 6379545167, type: 'private' } } }]).length === 0,
    'route: non-text message (sticker/photo) ignored');

  // Free text -> LLM with a full messages array (system ... user).
  reset();
  const tgChat = runRoute([tgMsg(5, 'thanks!')]);
  ok(tgChat.length === 1 && tgChat[0].json.needs_llm === true, 'route: free text -> needs_llm');
  const tgMsgs = tgChat[0].json.messages;
  ok(Array.isArray(tgMsgs) && tgMsgs[0].role === 'system' && /assistant/i.test(tgMsgs[0].content), 'route: chat builds messages, leading with the system prompt');
  ok(tgMsgs[tgMsgs.length - 1].role === 'user' && tgMsgs[tgMsgs.length - 1].content === 'thanks!', 'route: the new user message is last');
  reset();

  // /help and unknown command -> direct reply, no LLM.
  const tgHelp = runRoute([tgMsg(6, '/help')]);
  ok(tgHelp.length === 1 && tgHelp[0].json.needs_llm === false && /Second Brain/.test(tgHelp[0].json.reply), 'route: /help -> direct reply, no LLM');
  ok(runRoute([tgMsg(7, '/wat')])[0].json.reply.includes('Unknown'), 'route: unknown command -> guidance');
  reset();

  // /note writes a capture file to the inbox and confirms.
  const tgNote = runRoute([tgMsg(8, '/note buy <milk> & eggs')]);
  ok(tgNote[0].json.needs_llm === false && tgNote[0].json.reply.includes('Captured'), 'route: /note -> capture confirmation');
  const tgCaptures = fs.readdirSync(INBOX).filter((f) => f.endsWith('.md'));
  ok(tgCaptures.length === 1, 'route: /note actually wrote a .md capture file');
  const tgCapBody = fs.readFileSync(path.join(INBOX, tgCaptures[0]), 'utf8');
  ok(/source: telegram/.test(tgCapBody) && tgCapBody.includes('buy <milk> & eggs'), 'route: capture file tagged source: telegram, raw text preserved');
  reset();

  // /done appends to the action log (feeds the morning staleness filter) and escapes HTML.
  ok(runRoute([tgMsg(9, '/done a<b>')])[0].json.reply.includes('a&lt;b&gt;'), 'route: /done escapes < > in the echoed project name');
  const tgLog = fs.readFileSync(ACTIONS, 'utf8').trim();
  ok(/"action":"done"/.test(tgLog) && /a<b>/.test(tgLog), 'route: /done appends a done record to the action log');
  reset();

  // Offset advances past the highest update_id seen, so nothing ever replays.
  runRoute([tgMsg(10, 'a'), tgMsg(14, '/help')]);
  ok(fs.readFileSync(path.join(INBOX, '.tg_offset'), 'utf8').trim() === '15', 'route: offset advanced to max(update_id)+1');
  reset();

  // Extract Reply: HTML render + soft fallback (a chat turn must never go silent).
  ok(runExtractReply({ choices: [{ message: { content: '*hi* <x>' } }] })[0].json.reply === '<b>hi</b> &lt;x&gt;',
    'extract reply: *bold* -> <b>, < > escaped');
  ok(/could not generate/i.test(runExtractReply({ choices: [{ message: { content: '' }, finish_reason: 'length' }] })[0].json.reply),
    'extract reply: empty completion -> soft fallback, not a throw');

  // Send body + Get Updates URL wiring.
  const tgSb = evalExpr(tgSendBody, { reply: '<b>x</b>' }, { TELEGRAM_CHAT_ID: '6379545167' });
  ok(tgSb.chat_id === '6379545167' && tgSb.text === '<b>x</b>' && tgSb.parse_mode === 'HTML', 'send reply body: chat_id from $env, text, parse_mode HTML');
  ok(/getUpdates/.test(tgGetUrl) && /offset=/.test(tgGetUrl), 'get updates: URL polls getUpdates with an offset');
  // Low-latency wiring: long-poll (timeout>0) on a fast (seconds) cadence, and the
  // poll hold must stay below the schedule interval so two getUpdates never overlap.
  const tgTimeout = parseInt((tgGetUrl.match(/[?&]timeout=(\d+)/) || [])[1], 10);
  const tgInterval = nodeNamed(tgAssistant, 'Poll Every 5s').parameters.rule.interval[0];
  ok(tgTimeout >= 1, 'get updates: long-poll timeout > 0 (returns the instant a message arrives)');
  ok(tgInterval.field === 'seconds' && tgInterval.secondsInterval >= 1, 'poll cadence: seconds-based (not the old 1-minute lag)');
  ok(tgTimeout < tgInterval.secondsInterval, 'no overlap: poll hold stays under the schedule interval (single getUpdates consumer)');

  // ---------------------------------------------------------------- Round L (NEW)
  console.log('\n# Round L — grounded follow-ups (nudge writes focus, assistant reads it)');
  reset();
  put('projects/p.md', '---\ntype: project\ntitle: "Stripe billing"\npriority: high\nlast_actionable_date: ' + D(-20) + '\nstale_after_days: 5\n---\n\n## log\n- ' + D(-20) + ' wired sandbox keys');
  const fout = runFilterTg(runScan());
  ok(fout.length === 1, 'tg nudge filter: stale project produces a nudge request');
  const ctx = JSON.parse(fs.readFileSync(path.join(INBOX, '.tg_context.json'), 'utf8'));
  ok(ctx.projects && ctx.projects[0].title === 'Stripe billing', 'tg nudge: writes focus context (the nudged project) to disk');

  // With focus present, free text is grounded on that project (in the system msg).
  const grounded = runRoute([tgMsg(20, 'explain more')]);
  const gSys = grounded[0].json.messages[0].content;
  ok(grounded[0].json.needs_llm === true && /CURRENT FOCUS/.test(gSys), 'assistant: follow-up is grounded with CURRENT FOCUS');
  ok(/Stripe billing/.test(gSys), 'assistant: grounding carries the actual nudged project into the prompt');

  // No focus file -> plain assistant, no crash, no forced grounding.
  reset();
  const plain = runRoute([tgMsg(21, 'hello there')]);
  ok(plain[0].json.needs_llm === true && !/CURRENT FOCUS/.test(plain[0].json.messages[0].content), 'assistant: no focus file -> plain chat, no grounding');
  reset();

  // ---------------------------------------------------------------- Round M (NEW)
  console.log('\n# Round M — short-term conversation memory (bounded, self-resetting)');
  reset();
  // Turn 1: user says hello; the assistant reply is recorded by Extract Reply.
  runRoute([tgMsg(30, 'hello')]);
  runExtractReply({ choices: [{ message: { content: 'Hi! How can I help?' } }] });
  // Turn 2: prior turns must be replayed into the new prompt.
  const tgM2 = runRoute([tgMsg(31, 'and then?')])[0].json.messages;
  ok(tgM2.some((x) => x.role === 'assistant' && /How can I help/.test(x.content)), 'memory: prior assistant turn is replayed into the next prompt');
  ok(tgM2.some((x) => x.role === 'user' && x.content === 'hello'), 'memory: prior user turn is replayed');
  ok(tgM2[tgM2.length - 1].content === 'and then?', 'memory: the current message is always last');

  // A newer nudge focus starts a fresh thread (no stale bleed across days).
  reset();
  runRoute([tgMsg(40, 'one')]);
  runExtractReply({ choices: [{ message: { content: 'reply one' } }] });
  fs.writeFileSync(path.join(INBOX, '.tg_context.json'), JSON.stringify({ ts: new Date(Date.now() + 1000).toISOString(), today: '2026-06-25', projects: [{ title: 'New' }], reviews: [] }));
  const tgM3 = runRoute([tgMsg(41, 'two')])[0].json.messages;
  ok(!tgM3.some((x) => /reply one/.test(String(x.content))), 'memory: a newer nudge focus resets the conversation');

  // The window stays bounded no matter how long you chat.
  reset();
  for (let i = 0; i < 7; i++) { runRoute([tgMsg(50 + i, 'u' + i)]); runExtractReply({ choices: [{ message: { content: 'a' + i } }] }); }
  const tgHist = JSON.parse(fs.readFileSync(path.join(INBOX, '.tg_history.json'), 'utf8'));
  ok(tgHist.turns.length <= 8, 'memory: history is trimmed to a bounded window (no token blowup)');
  reset();

} finally {
  fs.rmSync(VAULT, { recursive: true, force: true });
  fs.rmSync(INBOX, { recursive: true, force: true });
}

console.log(`\n==== ${pass} passed, ${fail} failed ====`);
process.exit(fail ? 1 : 0);
