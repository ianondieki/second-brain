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
 * engine, the live Groq/Evolution endpoints, and Evolution's webhook delivery.
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

const morning = load('morning-nudge-workflow.json');
const inbound = load('inbound-capture-workflow.json');
const errwf = load('error-handler-workflow.json');
const nodeNamed = (wf, n) => wf.nodes.find((x) => x.name === n);
const codeOf = (wf, n) => nodeNamed(wf, n).parameters.jsCode;

// Hermetic temp dirs standing in for the container mounts.
const VAULT = fs.mkdtempSync(path.join(os.tmpdir(), 'sb-vault-'));
const INBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'sb-inbox-'));
const ACTIONS = path.join(INBOX, '.actions.jsonl');

// Rebind hardcoded container paths to the temp dirs, then compile the shipped code.
const scanCode = codeOf(morning, 'Scan & Read Vault').replace("'/data/vault'", JSON.stringify(VAULT));
const filterCode = codeOf(morning, 'Filter Stale Projects').replace("'/data/inbox/.actions.jsonl'", JSON.stringify(ACTIONS));
const handleCode = codeOf(inbound, 'Handle Command').replace("'/data/inbox'", JSON.stringify(INBOX));
const errorCode = codeOf(errwf, 'Format Alert');
const extractCode = codeOf(morning, 'Extract Nudge');
const groqBody = nodeNamed(morning, 'Cloud LLM Synthesis (Groq)').parameters.jsonBody;
const evoBody = nodeNamed(morning, 'Send to WhatsApp Gateway').parameters.jsonBody;

// Telegram delivery variant — same pipeline, HTML-rendering Extract + Telegram send.
const telegram = load('morning-nudge-telegram.json');
const extractTgCode = codeOf(telegram, 'Extract Nudge');
const tgBody = nodeNamed(telegram, 'Send to Telegram').parameters.jsonBody;
const filterTgCode = codeOf(telegram, 'Filter Stale Projects')
  .replace("'/data/inbox/.actions.jsonl'", JSON.stringify(ACTIONS))
  .replace("'/data/inbox/.tg_context.json'", JSON.stringify(path.join(INBOX, '.tg_context.json')));

// Two-way Telegram assistant — polling getUpdates, owner-only, commands + chat.
const tgAssistant = load('telegram-assistant-workflow.json');
const routeCode = codeOf(tgAssistant, 'Route & Handle').replace("'/data/inbox'", JSON.stringify(INBOX));
const readOffsetCode = codeOf(tgAssistant, 'Read Offset').replace("'/data/inbox/.tg_offset'", JSON.stringify(path.join(INBOX, '.tg_offset')));
const extractReplyCode = codeOf(tgAssistant, 'Extract Reply');
const tgSendBody = nodeNamed(tgAssistant, 'Send Reply').parameters.jsonBody;
const tgGetUrl = nodeNamed(tgAssistant, 'Get Updates').parameters.url;

const runScan = () => new Function('require', scanCode)(require);
const runFilter = (items) => new Function('$input', 'require', filterCode)({ all: () => items }, require);
const runHandle = (items) => new Function('$input', 'require', '$env', handleCode)({ all: () => items }, require, env);
const runError = (item) => new Function('$input', errorCode)({ first: () => item });
const runExtract = (json) => new Function('$input', extractCode)({ first: () => ({ json }) });
const runExtractTg = (json) => new Function('$input', extractTgCode)({ first: () => ({ json }) });
const tgEnv = { TELEGRAM_CHAT_ID: '6379545167' };
const runRoute = (result) => new Function('$input', 'require', '$env', routeCode)({ first: () => ({ json: { result } }) }, require, tgEnv);
const runReadOffset = () => new Function('require', readOffsetCode)(require);
const runFilterTg = (items) => new Function('$input', 'require', filterTgCode)({ all: () => items }, require);
const runExtractReply = (json) => new Function('$input', extractReplyCode)({ first: () => ({ json }) });
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

const env = { GROQ_API_KEY: 'gk', EVOLUTION_API_KEY: 'ek', EVOLUTION_INSTANCE: 'secondbrain', WA_TARGET_NUMBER: '2348012345678' };

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
  const mock = { text: '🧊 *HOOK*\nYour _BOM note_ went cold.' };
  const e = JSON.parse(JSON.stringify(evalExpr(evoBody, mock, env)));
  ok(e.number === '2348012345678' && e.text === mock.text && e.delay === 1200, 'Evolution body intact (number from $env, normalized text, delay)');

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
  console.log('\n# Round E — WhatsApp action-log overrides (touch / done / stale)');
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

  // ---------------------------------------------------------------- Round F (NEW)
  console.log('\n# Round F — inbound command handler');
  reset();
  const wh = (text, jid = '2348012345678@s.whatsapp.net') => ({ json: { body: { event: 'messages.upsert', data: { key: { remoteJid: jid, fromMe: false }, message: { conversation: text } } } } });
  const r1 = runHandle([wh('/note Call the accountant about Q3 VAT')]);
  ok(r1.length === 1 && /Captured/.test(r1[0].json.reply), '/note returns a capture confirmation');
  const captured = fs.readdirSync(INBOX).filter((f) => f.endsWith('.md'));
  ok(captured.length === 1, '/note wrote exactly one markdown file to the inbox');
  const capBody = fs.readFileSync(path.join(INBOX, captured[0]), 'utf8');
  ok(/type: capture/.test(capBody) && /Q3 VAT/.test(capBody), 'captured note has type:capture frontmatter + the text');
  const r2 = runHandle([wh('/touch Stripe billing')]);
  ok(/reset/.test(r2[0].json.reply) && /"action":"touch"/.test(fs.readFileSync(ACTIONS, 'utf8')), '/touch appends a touch record');
  const r3 = runHandle([wh('/done Old idea')]);
  ok(/done/.test(r3[0].json.reply) && /"action":"done"/.test(fs.readFileSync(ACTIONS, 'utf8')), '/done appends a done record');
  ok(runHandle([wh('🧊 *HOOK* your project went cold')]).length === 0, 'the bot\'s own nudge (no leading /) is ignored -> no loop');
  ok(runHandle([wh('just a random thought')]).length === 0, 'plain text without a command is ignored');
  ok(/commands/i.test(runHandle([wh('/help')])[0].json.reply), '/help lists the commands');
  ok(/Unknown/.test(runHandle([wh('/frobnicate x')])[0].json.reply), 'unknown command -> friendly error');
  ok(runHandle([wh('/note')])[0].json.reply.includes('Unknown') || runHandle([wh('/note')]).length >= 0, '/note with no text does not crash');
  const r4 = runHandle([wh('/done Stripe')]);
  ok(r4[0].json.number === '2348012345678', 'reply targets the sender number (jid stripped)');
  ok(runHandle([wh('/note hijack', '19998887777@s.whatsapp.net')]).length === 0, 'command from a NON-owner number is ignored (owner-only)');
  ok(runHandle([wh('/help', '120363999@g.us')]).length === 0, 'group message is ignored');
  ok(runHandle([wh('/help', 'status@broadcast')]).length === 0, 'status broadcast is ignored');

  // ---------------------------------------------------------------- Round G (NEW)
  console.log('\n# Round G — error-handler formatting');
  const alert = runError({ json: { workflow: { name: 'Autonomous Morning Nudge Pipeline' }, execution: { lastNodeExecuted: 'Cloud LLM Synthesis (Groq)', error: { message: 'Request failed with status code 401' }, url: 'http://localhost:5678/execution/42' } } });
  const at = alert[0].json.text;
  ok(/Second Brain failed/.test(at) && /Morning Nudge/.test(at) && /401/.test(at) && /execution\/42/.test(at), 'error alert includes workflow, node, message, url');
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
  ok(xThrew && /no usable text/.test(xMsg), 'empty completion throws (no blank WhatsApp send)');
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

  // Free text -> LLM with the chat system prompt.
  const tgChat = runRoute([tgMsg(5, 'thanks!')]);
  ok(tgChat.length === 1 && tgChat[0].json.needs_llm === true, 'route: free text -> needs_llm');
  ok(tgChat[0].json.user === 'thanks!' && /assistant/i.test(tgChat[0].json.system), 'route: chat carries user text + system prompt');
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

  // ---------------------------------------------------------------- Round L (NEW)
  console.log('\n# Round L — grounded follow-ups (nudge writes focus, assistant reads it)');
  reset();
  put('projects/p.md', '---\ntype: project\ntitle: "Stripe billing"\npriority: high\nlast_actionable_date: ' + D(-20) + '\nstale_after_days: 5\n---\n\n## log\n- ' + D(-20) + ' wired sandbox keys');
  const fout = runFilterTg(runScan());
  ok(fout.length === 1, 'tg nudge filter: stale project produces a nudge request');
  const ctx = JSON.parse(fs.readFileSync(path.join(INBOX, '.tg_context.json'), 'utf8'));
  ok(ctx.projects && ctx.projects[0].title === 'Stripe billing', 'tg nudge: writes focus context (the nudged project) to disk');

  // With focus present, free text is grounded on that project.
  const grounded = runRoute([tgMsg(20, 'explain more')]);
  ok(grounded[0].json.needs_llm === true && /CURRENT FOCUS/.test(grounded[0].json.system), 'assistant: follow-up is grounded with CURRENT FOCUS');
  ok(/Stripe billing/.test(grounded[0].json.system), 'assistant: grounding carries the actual nudged project into the prompt');

  // No focus file -> plain assistant, no crash, no forced grounding.
  reset();
  const plain = runRoute([tgMsg(21, 'hello there')]);
  ok(plain[0].json.needs_llm === true && !/CURRENT FOCUS/.test(plain[0].json.system), 'assistant: no focus file -> plain chat, no grounding');
  reset();

} finally {
  fs.rmSync(VAULT, { recursive: true, force: true });
  fs.rmSync(INBOX, { recursive: true, force: true });
}

console.log(`\n==== ${pass} passed, ${fail} failed ====`);
process.exit(fail ? 1 : 0);
