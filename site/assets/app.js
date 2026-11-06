// yellow-agents showcase. Every number and byte on this page comes from site/data/*.json,
// exported by the Python package (yellow-baseline, yellow-site-data). Nothing is invented here.

const LOCALES = ["pt-BR", "en", "es", "zh", "ar"];
const RTL = new Set(["ar"]);
const SNAPSHOTS = ["bedroom", "oak_stops_you", "oak_battle_menu", "got_pikachu"];
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

let L = {};          // current locale strings
let lang = "pt-BR";
let data = {};
const timers = {};

// ---------------------------------------------------------------- utils
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const t = (key, vars = {}) => {
  const v = key.split(".").reduce((o, k) => (o == null ? o : o[k]), L);
  if (typeof v !== "string") return v ?? key;
  return v.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? vars[k] : `{${k}}`));
};
const num = (n, opts) => new Intl.NumberFormat(lang, opts).format(n);
const getJSON = (path) => fetch(path).then((r) => {
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
});
function loop(name, fn, ms) {
  clearInterval(timers[name]);
  timers[name] = reduceMotion ? null : setInterval(fn, ms);
}
function stop(name) { clearInterval(timers[name]); timers[name] = null; }

// ---------------------------------------------------------------- i18n
function pickLocale() {
  const q = new URLSearchParams(location.search).get("lang");
  const saved = localStorage.getItem("lang");
  const nav = (navigator.languages || [navigator.language]).map((l) => (l.startsWith("pt") ? "pt-BR" : l.slice(0, 2)));
  return [q, saved, ...nav].find((l) => LOCALES.includes(l)) || "pt-BR";
}

async function setLocale(next) {
  L = await getJSON(`i18n/${next}.json`);
  lang = next;
  localStorage.setItem("lang", next);
  document.documentElement.lang = next;
  document.documentElement.dir = RTL.has(next) ? "rtl" : "ltr";
  $("#lang").value = next;
  document.title = t("meta.title");
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  renderAll();
}

// ---------------------------------------------------------------- hero + layers
function renderStatus() {
  const b = data.baseline;
  const cost = data.sessions.reduce((s, x) => s + (x.meta.custo_usd || 0), 0);
  const w = data.walking.closed_loop;
  const items = [
    [num(b.total_frames), t("status.frames")],
    [`${w.correct}/${w.total}`, t("status.steps")],
    [num(data.sessions.length), t("status.sessions")],
    [num(cost, { style: "currency", currency: "USD" }), t("status.cost")],
  ];
  $("#status").innerHTML = items.map(([v, l]) => `<li><b>${esc(v)}</b><span>${esc(l)}</span></li>`).join("");
}

function renderLayers() {
  const layers = t("how.layers");
  $("#layers").innerHTML = layers.map((l) => `
    <li class="${l.soon ? "soon" : ""}"><div><strong>${esc(l.name)}</strong><code>${esc(l.code)}</code></div><p>${esc(l.text)}</p></li>`).join("");
  const items = [...document.querySelectorAll("#layers li:not(.soon)")];
  let i = 0;
  const tick = () => { items.forEach((el, k) => el.classList.toggle("on", k === i)); i = (i + 1) % items.length; };
  tick();
  loop("layers", tick, 1400);
}

// ---------------------------------------------------------------- walking
function renderWalk() {
  const w = data.walking;
  const rows = w.fixed.map((f) => {
    const ok = f.tiles.filter((x) => x === 1).length;
    const tiles = f.tiles.map((x) => `<span class="tile ${x === 1 ? "ok" : "miss"}" title="${x}">${x}</span>`).join("");
    const note = f.note ? ` · ${t("walk.oldDefault")}` : "";
    return `<div class="walk-row"><span class="lbl">${t("walk.fixed", { hold: f.hold, settle: f.settle })}${note}</span><div class="tiles">${tiles}</div><span class="val">${ok}/${f.tiles.length}</span></div>`;
  });
  const c = w.closed_loop;
  const closed = Array.from({ length: c.total }, () => `<span class="tile ok"></span>`).join("");
  rows.push(`<div class="walk-row closed"><span class="lbl">${esc(t("walk.closed"))}</span><div class="tiles dense">${closed}</div><span class="val">${c.correct}/${c.total}</span></div>`);
  $("#walk").innerHTML = rows.join("") + `<p class="walk-legend">${esc(t("walk.legend", { moved: c.moved, blocked: c.blocked, warped: c.warped }))}</p>`;
  $("#walk-source").innerHTML = `${esc(t("label.source"))}: <code>${esc(w.source)}</code>`;
}

// ---------------------------------------------------------------- RAM decoder
const dec = { snap: 0, field: 0, fields: [] };

function resolvePath(state, path) {
  return path.split(".").reduce((o, part) => {
    if (o == null) return o;
    const m = part.match(/^(\w+)\[(\d+)\]$/);
    return m ? (o[m[1]] || [])[+m[2]] : o[part];
  }, state);
}

function fieldValue(state, path) {
  if (path === "party") return state.party.length;
  if (path === "screen.lines") return state.screen.lines;
  if (path === "battle.kind") return state.battle ? state.battle.kind : null;
  return resolvePath(state, path);
}

function renderDecoderTabs() {
  $("#snap-tabs").innerHTML = SNAPSHOTS.map((name, i) =>
    `<button type="button" role="tab" aria-selected="${i === dec.snap}" data-i="${i}">${esc(t(`ms.${name}`))}</button>`).join("");
  document.querySelectorAll("#snap-tabs button").forEach((b) => b.addEventListener("click", () => {
    dec.snap = +b.dataset.i; dec.field = 0; renderDecoder(); playDecoder(true);
  }));
}

function renderDecoder() {
  renderDecoderTabs();
  const snap = data.snapshots[dec.snap];
  dec.fields = [];
  $("#hex").innerHTML = snap.regions.filter((r) => r.hex.length).map((r, ri) => {
    const bytes = r.hex.match(/../g);
    const owner = new Array(bytes.length).fill(-1);
    r.fields.forEach((f) => {
      const id = dec.fields.length;
      dec.fields.push({ ...f, region: r, ri });
      for (let k = f.offset; k < f.offset + f.length; k++) owner[k] = id;
    });
    const cells = bytes.map((b, k) => `<span class="byte ${owner[k] >= 0 ? "in-field" : ""}" data-f="${owner[k]}">${b}</span>`).join("");
    const grid = r.symbol === "wTileMap" ? " grid" : "";
    return `<div class="region"><div class="region-name"><b>${esc(r.symbol)}</b> @ ${r.address.toString(16).padStart(4, "0")} · ${bytes.length} B</div><div class="bytes${grid}">${cells}</div></div>`;
  }).join("");
  showField();
}

function stateLines(state) {
  return JSON.stringify(state, null, 1).split("\n");
}

function showField() {
  const snap = data.snapshots[dec.snap];
  const f = dec.fields[dec.field];
  document.querySelectorAll("#hex .byte").forEach((el) => el.classList.toggle("hl", +el.dataset.f === dec.field));
  const hlEl = document.querySelector(`#hex .byte[data-f="${dec.field}"]`);
  if (hlEl) {
    const box = $("#hex");
    const top = hlEl.offsetTop - box.offsetTop;
    if (top < box.scrollTop || top > box.scrollTop + box.clientHeight - 30) box.scrollTop = top - 40;
  }
  const raw = f.region.hex.slice(f.offset * 2, (f.offset + f.length) * 2);
  const value = fieldValue(snap.state, f.path);
  const shown = JSON.stringify(value);
  const rawShown = raw.length > 48 ? `${raw.slice(0, 48)}… (${f.length} B)` : raw.match(/../g).join(" ");
  $("#field").innerHTML = `
    <div class="path">${esc(f.path)}</div>
    <div class="raw">${esc(rawShown)}</div>
    <div class="arrow">↓ ${f.note ? `<span class="note">${esc(f.note)}</span>` : ""}</div>
    <div class="value">${esc(shown && shown.length > 240 ? shown.slice(0, 240) + "…" : shown)}</div>`;
  // highlight the top-level key of the path in the state JSON
  const root = f.path.split(/[.[]/)[0];
  const lines = stateLines(snap.state);
  let inside = false;
  const html = lines.map((line) => {
    if (/^ "/.test(line)) inside = line.startsWith(` "${root}":`);
    return inside ? `<span class="hl">${esc(line)}</span>` : esc(line);
  }).join("\n");
  const pre = $("#state-json");
  pre.innerHTML = html;
  const first = pre.querySelector(".hl");
  if (first) pre.scrollTop = first.offsetTop - pre.offsetTop - 20;
}

function stepDecoder(d) {
  dec.field = (dec.field + d + dec.fields.length) % dec.fields.length;
  showField();
}

function playDecoder(on) {
  if (on) { loop("dec", () => stepDecoder(1), 2200); } else { stop("dec"); }
  $("#dec-play").textContent = timers.dec ? t("ctl.pause") : t("ctl.play");
}

// ---------------------------------------------------------------- MCP flow
const flow = { call: 0, phase: 0 };
const LANE_X = [16.6, 50, 83.3]; // centre of each lane, %

function flowPhases(call) {
  // client -> server (validate) -> emulator -> client; a rejected call never reaches the emulator
  return call.is_error ? [0, 1, 0] : [0, 1, 2, 1, 0];
}

function showFlow() {
  const call = data.mcp[flow.call];
  const phases = flowPhases(call);
  const lane = phases[flow.phase];
  const back = flow.phase >= phases.length / 2;
  const done = flow.phase === phases.length - 1;
  document.querySelectorAll(".lane").forEach((el, i) => el.classList.toggle("active", i === lane));
  const pk = $("#packet");
  pk.style.left = `calc(${LANE_X[lane]}% - 7px)`;
  pk.classList.toggle("err", call.is_error && back);
  $("#flow-req").textContent = JSON.stringify({ tool: call.tool, arguments: call.arguments }, null, 1);
  const img = $("#flow-img");
  if (done) {
    const res = call.result;
    $("#flow-res").textContent = typeof res === "string" ? res : JSON.stringify(res, null, 1);
    img.hidden = !(res && res.file);
    if (res && res.file) img.src = res.file;
  } else {
    $("#flow-res").textContent = "…";
    img.hidden = true;
  }
  const n = t(`mcp.note.${call.is_error ? "error" : call.tool}`);
  const cls = call.is_error ? "err" : "ok";
  $("#flow-note").innerHTML = `<b>${flow.call + 1}/${data.mcp.length} · ${esc(call.tool)}</b> — ${esc(n)}${done ? ` <span class="${cls}">· ${esc(t("mcp.latency", { ms: num(call.latency_ms) }))}</span>` : ""}`;
}

function stepFlow(d) {
  const phases = flowPhases(data.mcp[flow.call]);
  flow.phase += d;
  if (flow.phase >= phases.length) { flow.call = (flow.call + 1) % data.mcp.length; flow.phase = 0; }
  if (flow.phase < 0) { flow.call = (flow.call - 1 + data.mcp.length) % data.mcp.length; flow.phase = flowPhases(data.mcp[flow.call]).length - 1; }
  showFlow();
}

function playFlow(on) {
  if (on) { loop("flow", () => stepFlow(1), 1100); } else { stop("flow"); }
  $("#flow-play").textContent = timers.flow ? t("ctl.pause") : t("ctl.play");
}

// ---------------------------------------------------------------- baseline milestones
function renderMilestones() {
  const b = data.baseline;
  const max = b.total_frames;
  const box = $("#milestones");
  let html = `<div class="ms-axis"></div><div class="ms-fill" id="ms-fill"></div>`;
  // Labels go in 4 rows (2 above the axis, 2 below); each takes the first row where it fits.
  const width = box.clientWidth || 1000;
  const LABEL_W = 120;
  const ROWS = [{ top: 52, tick: 62 }, { top: 140, tick: 128 }, { top: 8, tick: 18 }, { top: 176, tick: 128 }];
  const rowEnd = ROWS.map(() => -Infinity);
  b.milestones.forEach((m, i) => {
    const x = (m.frame / max) * 100;
    const px = (x / 100) * width;
    let r = rowEnd.findIndex((end) => px - LABEL_W / 2 > end + 8);
    if (r < 0) r = 0;
    rowEnd[r] = px + LABEL_W / 2;
    const row = ROWS[r];
    const above = row.top < 120;
    const tickTop = above ? row.tick + 30 : 128;
    const tickH = above ? 114 - tickTop : row.top - 128;
    html += `<div class="ms-tick" style="inset-inline-start:${x}%;top:${tickTop}px;height:${Math.max(tickH, 0)}px"></div>`;
    html += `<div class="ms" style="inset-inline-start:${x}%" data-i="${i}" tabindex="0"></div>`;
    html += `<div class="ms-label${x > 88 ? " end" : ""}${x < 6 ? " start" : ""}" style="inset-inline-start:${x}%;top:${row.top}px"><b>${num(m.frame)}</b>${esc(t(`ms.${m.name}`))}</div>`;
  });
  html += `<div class="ms-scale" style="inset-inline-start:0">0</div><div class="ms-scale" style="inset-inline-end:0">${esc(t("baseline.frames", { n: num(max), s: num(max / 60, { maximumFractionDigits: 0 }) }))}</div>`;
  box.innerHTML = html;
  requestAnimationFrame(() => { $("#ms-fill").style.width = "100%"; });
  const tip = $("#tooltip");
  box.querySelectorAll(".ms").forEach((el) => {
    const m = b.milestones[+el.dataset.i];
    const show = () => {
      const r = el.getBoundingClientRect();
      tip.innerHTML = `<b>${esc(t(`ms.${m.name}`))}</b><br>${esc(t("baseline.tip", { frame: num(m.frame), s: num(m.frame / 60, { maximumFractionDigits: 1 }), map: m.map_name, x: m.x, y: m.y }))}`;
      tip.hidden = false;
      tip.style.left = `${Math.min(r.left, innerWidth - 270)}px`;
      tip.style.top = `${r.top - tip.offsetHeight - 10}px`;
    };
    el.addEventListener("mouseenter", show);
    el.addEventListener("focus", show);
    el.addEventListener("mouseleave", () => { tip.hidden = true; });
    el.addEventListener("blur", () => { tip.hidden = true; });
  });
  $("#milestone-table").innerHTML = `<tr><th>${esc(t("baseline.col.milestone"))}</th><th>${esc(t("baseline.col.frame"))}</th><th>${esc(t("baseline.col.where"))}</th></tr>` +
    b.milestones.map((m) => `<tr><td>${esc(t(`ms.${m.name}`))}</td><td class="num">${num(m.frame)}</td><td><code>${esc(m.map_name)} (${m.x},${m.y})</code></td></tr>`).join("");
}

// ---------------------------------------------------------------- journal
function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, txt, href) => {
      const url = /^https?:/.test(href) ? href : `https://github.com/andrR89/yellow-agents/blob/main/docs/sessions/${href}`;
      return `<a href="${url}">${txt}</a>`;
    });
}

function markdown(md) {
  // Enough markdown for docs/sessions: headings, lists (with continuation lines), tables, paragraphs.
  const out = [];
  let list = null, para = [], table = null;
  const flush = () => {
    if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; }
    if (list) { out.push(`<ul>${list.map((i) => `<li>${inline(i)}</li>`).join("")}</ul>`); list = null; }
    if (table) {
      const rows = table.filter((r) => !/^\|[\s|:-]+\|$/.test(r)).map((r) => r.slice(1, -1).split("|").map((c) => c.trim()));
      out.push(`<table>${rows.map((r, i) => `<tr>${r.map((c) => (i ? `<td>${inline(c)}</td>` : `<th>${inline(c)}</th>`)).join("")}</tr>`).join("")}</table>`);
      table = null;
    }
  };
  for (const raw of md.split("\n")) {
    const line = raw.trimEnd();
    let m;
    if (!line.trim()) { flush(); continue; }
    if ((m = line.match(/^(#{2,4}) (.*)/))) { flush(); const h = Math.min(m[1].length, 3); out.push(`<h${h}>${inline(m[2])}</h${h}>`); continue; }
    if (line.startsWith("|")) { if (!table) { flush(); table = []; } table.push(line); continue; }
    if ((m = line.match(/^\s*- (.*)/))) { if (para.length) flush(); list = list || []; list.push(m[1]); continue; }
    if (list && /^\s{2,}\S/.test(line)) { list[list.length - 1] += " " + line.trim(); continue; }
    para.push(line.trim());
  }
  flush();
  return out.join("\n");
}

function renderJournal() {
  const note = lang === "pt-BR" ? "" : `<p class="journal-lang">${esc(t("journal.ptOnly"))}</p>`;
  $("#timeline").innerHTML = data.sessions.slice().reverse().map((s, i) => {
    const m = s.meta;
    const metaLine = [t("journal.session", { n: m.sessao }), m.data, t("journal.phase", { n: m.fase }),
      m.duracao_h == null ? t("journal.notMeasured") : t("journal.hours", { h: num(m.duracao_h) }),
      num(m.custo_usd || 0, { style: "currency", currency: "USD" })].join(" · ");
    return `<li><details ${i === 0 ? "open" : ""}><summary><span class="meta">${esc(metaLine)}</span><span class="ttl" lang="pt-BR">${esc(m.titulo)}</span>${m.marco ? `<span class="marco" lang="pt-BR">★ ${esc(m.marco)}</span>` : ""}</summary>${note}<div class="md" lang="pt-BR" dir="ltr">${markdown(s.body)}</div></details></li>`;
  }).join("");
}

// ---------------------------------------------------------------- wiring
function renderAll() {
  renderStatus();
  renderLayers();
  renderWalk();
  renderDecoder();
  playDecoder(!reduceMotion);
  showFlow();
  playFlow(!reduceMotion);
  renderMilestones();
  renderJournal();
}

async function main() {
  const [baseline, walking, sessions, mcp, ...snaps] = await Promise.all([
    getJSON("data/baseline.json"), getJSON("data/walking.json"), getJSON("data/sessions.json"),
    getJSON("data/mcp_flow.json"), ...SNAPSHOTS.map((n) => getJSON(`data/snapshots/${n}.json`)),
  ]);
  data = { baseline, walking, sessions, mcp, snapshots: snaps };
  $("#lang").addEventListener("change", (e) => setLocale(e.target.value));
  $("#dec-prev").addEventListener("click", () => { playDecoder(false); stepDecoder(-1); });
  $("#dec-next").addEventListener("click", () => { playDecoder(false); stepDecoder(1); });
  $("#dec-play").addEventListener("click", () => playDecoder(!timers.dec));
  $("#flow-prev").addEventListener("click", () => { playFlow(false); stepFlow(-1); });
  $("#flow-next").addEventListener("click", () => { playFlow(false); stepFlow(1); });
  $("#flow-play").addEventListener("click", () => playFlow(!timers.flow));
  await setLocale(pickLocale());
}

main().catch((err) => {
  document.querySelector("main").insertAdjacentHTML("afterbegin", `<p style="color:#ff7a7a">${esc(err.message)}</p>`);
});
