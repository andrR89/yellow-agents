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
    [num(data.replay.total_frames), t("status.runFrames", { name: data.replay.player_name })],
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

// ---------------------------------------------------------------- run replay + comparison
const rp = { i: 0 };
const SERIES = { baseline: "var(--s-baseline)", run: "var(--s-run)" };

function showStep() {
  const r = data.replay;
  const s = r.steps[rp.i];
  const img = $("#rp-img");
  if (s.screenshot) { img.src = s.screenshot; img.alt = t("replay.alt", { map: s.map_name, x: s.x, y: s.y }); }
  $("#rp-caption").textContent = t("replay.caption", { i: rp.i + 1, n: r.steps.length, frame: num(s.frame), tool: s.action.tool });
  $("#rp-action").textContent = JSON.stringify(s.action, null, 1);
  const lines = s.screen.lines.length ? s.screen.lines.join(" / ") : "—";
  const rows = [
    ["map", `${s.map_name} (${s.x},${s.y}) ${s.facing}`],
    ["screen", s.screen.cursor ? `${s.screen.kind} ▶ ${s.screen.cursor}` : s.screen.kind],
    ["text", lines],
    ["party", s.party.length ? s.party.join(", ") : "—"],
    ["battle", s.battle],
  ];
  if (s.stop) rows.unshift(["stop", s.stop]);
  $("#rp-state").innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
  const said = $("#rp-said");
  said.hidden = !(s.model || s.error);
  if (!said.hidden) {
    const meta = s.model ? t("replay.modelMeta", { model: shortModel(s.model), inTok: num(s.input_tokens), outTok: num(s.output_tokens),
      cost: num(s.cost_usd, { style: "currency", currency: "USD", maximumFractionDigits: 4 }) }) : "";
    said.innerHTML = `<h5>${esc(t("replay.said"))}</h5>${s.said ? `<p>${esc(s.said)}</p>` : ""}${s.error ? `<p class="err">${esc(s.error)}</p>` : ""}<p class="meta">${esc(meta)}</p>`;
  }
  $("#rp-scrub").value = rp.i;
  document.querySelectorAll("#rp-jumps button").forEach((b) => b.classList.toggle("on", +b.dataset.step <= rp.i && rp.i < +b.dataset.until));
}

function stepReplay(d) {
  const n = data.replay.steps.length;
  rp.i = (rp.i + d + n) % n;
  showStep();
}

function playReplay(on) {
  if (on) { loop("rp", () => stepReplay(1), 450); } else { stop("rp"); }
  $("#rp-play").textContent = timers.rp ? t("ctl.pause") : t("ctl.play");
}

function shortModel(spec) {
  const s = spec || "";
  return s.slice(s.indexOf(":") + 1).split("/").pop(); // "ollama:llama3.1:8b" -> "llama3.1:8b"
}

// in the order they happen in the game
const SCENARIO_ORDER = ["mcp", "pikachu", "rival_battle", "route1"];
const runModel = (e) => (e.source === "mcp" ? "mcp" : e.model);
const runScenario = (e) => (e.source === "mcp" ? "mcp" : e.scenario);

function modelLabel(key) {
  if (key === "mcp") return t("replay.who.mcp");
  return key.startsWith("ollama:") ? `${shortModel(key)} · ${t("replay.local")}` : shortModel(key);
}

const STAGE = { mcp: 1, pikachu: 1, rival_battle: 2, route1: 3 };

function scenarioLabel(scenario) {
  const name = scenario === "mcp" ? t("replay.run.mcp") : t(`bench.scenario.${scenario}`);
  return `${num(STAGE[scenario])} · ${name}`;
}

// model -> scenario -> latest run entry (run ids sort by time)
function runTable() {
  const table = new Map();
  for (const e of data.runs) {
    const m = runModel(e);
    if (!table.has(m)) table.set(m, new Map());
    table.get(m).set(runScenario(e), e);
  }
  const rank = (m) => (m === "mcp" ? 0 : m.startsWith("ollama:") ? 2 : 1);
  return new Map([...table].sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b)));
}

function fillScenarios(model, wanted) {
  const byScenario = data.runTable.get(model);
  const scenarios = [...byScenario.keys()].sort((a, b) => SCENARIO_ORDER.indexOf(a) - SCENARIO_ORDER.indexOf(b));
  $("#rp-scen").innerHTML = scenarios.map((s) => `<option value="${esc(byScenario.get(s).run_id)}">${esc(scenarioLabel(s))}</option>`).join("");
  const keep = byScenario.get(wanted) || byScenario.get(scenarios[0]);
  $("#rp-scen").value = keep.run_id;
  return keep.run_id;
}

function syncPickers(runId) {
  const entry = data.runs.find((e) => e.run_id === runId);
  $("#rp-model").value = runModel(entry);
  fillScenarios(runModel(entry), runScenario(entry));
}

async function selectRun(runId, scroll = false) {
  playReplay(false);
  data.replay = data.runCache[runId] || (data.runCache[runId] = await getJSON(`data/runs/${runId}.json`));
  syncPickers(runId);
  rp.i = 0;
  renderPlayer();
  if (scroll) $("#replay").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth" });
}

function renderReplay() {
  data.runTable = runTable();
  $("#rp-model").innerHTML = [...data.runTable.keys()].map((m) => `<option value="${esc(m)}">${esc(modelLabel(m))}</option>`).join("");
  syncPickers(data.replay.run_id);
  renderPlayer();
  renderCompare();
}

function renderPlayer() {
  const r = data.replay;
  $("#rp-scrub").max = r.steps.length - 1;
  $("#rp-action-title").textContent = t(r.source === "mcp" ? "replay.action" : "replay.actionAgent");
  // Milestones are the baseline's (new game -> Pikachu): they only mean something on such runs.
  const fromNewGame = r.source === "mcp" || (r.notes && r.notes.scenario === "pikachu");
  const ms = fromNewGame ? r.milestones : [];
  $("#rp-jumps").innerHTML = ms.map((m, k) => {
    const until = k + 1 < ms.length ? ms[k + 1].step : r.steps.length;
    return `<button type="button" data-step="${m.step}" data-until="${until}">${esc(t(`ms.${m.name}`))}</button>`;
  }).join("");
  document.querySelectorAll("#rp-jumps button").forEach((b) => b.addEventListener("click", () => {
    playReplay(false); rp.i = +b.dataset.step; showStep();
  }));
  showStep();
}

function renderCompare() {
  const r = data.mcpRun, b = data.baseline;
  const base = Object.fromEntries(b.milestones.map((m) => [m.name, m]));
  const rows = r.milestones.filter((m) => base[m.name]).map((m) => ({ name: m.name, run: m.frame, base: base[m.name].frame }));
  const max = Math.ceil(Math.max(...rows.flatMap((x) => [x.run, x.base])) / 5000) * 5000;
  const pct = (f) => (f / max) * 100;
  const names = { baseline: t("replay.series.baseline"), run: t("replay.series.run", { name: r.player_name }) };
  $("#cmp-legend").innerHTML = Object.keys(SERIES).map((k) => `<span><i style="background:${SERIES[k]}"></i>${esc(names[k])}</span>`).join("");
  let grid = "";
  for (let f = 0; f <= max; f += 5000) grid += `<div class="cmp-grid" style="left:${pct(f)}%"><span>${num(f)}</span></div>`;
  $("#cmp").innerHTML = `<div class="cmp-plot">${grid}${rows.map((x, i) => {
    const lo = Math.min(x.run, x.base), hi = Math.max(x.run, x.base);
    const d = x.run - x.base;
    return `<div class="cmp-row"><span class="cmp-lbl">${esc(t(`ms.${x.name}`))}</span><div class="cmp-track">
      <div class="cmp-gap" style="left:${pct(lo)}%;width:${pct(hi) - pct(lo)}%"></div>
      <button type="button" class="cmp-dot" style="left:${pct(x.base)}%;background:${SERIES.baseline}" data-i="${i}" data-s="baseline"></button>
      <button type="button" class="cmp-dot" style="left:${pct(x.run)}%;background:${SERIES.run}" data-i="${i}" data-s="run"></button>
      </div><span class="cmp-delta ${d > 0 ? "worse" : "better"}">${d > 0 ? "+" : ""}${num(d)}</span></div>`;
  }).join("")}</div>`;
  const tip = $("#tooltip");
  document.querySelectorAll(".cmp-dot").forEach((el) => {
    const x = rows[+el.dataset.i];
    const f = el.dataset.s === "run" ? x.run : x.base;
    el.setAttribute("aria-label", `${names[el.dataset.s]} · ${t(`ms.${x.name}`)} · ${num(f)}`);
    const show = () => {
      const rc = el.getBoundingClientRect();
      tip.innerHTML = `<b>${esc(t(`ms.${x.name}`))}</b><br>${esc(names[el.dataset.s])}: ${esc(t("replay.tip", { frame: num(f), s: num(f / 60, { maximumFractionDigits: 1 }) }))}`;
      tip.hidden = false;
      tip.style.left = `${Math.min(rc.left, innerWidth - 270)}px`;
      tip.style.top = `${rc.top - tip.offsetHeight - 10}px`;
    };
    el.addEventListener("mouseenter", show);
    el.addEventListener("focus", show);
    el.addEventListener("mouseleave", () => { tip.hidden = true; });
    el.addEventListener("blur", () => { tip.hidden = true; });
  });
  $("#cmp-table").innerHTML = `<tr><th>${esc(t("baseline.col.milestone"))}</th><th>${esc(names.baseline)}</th><th>${esc(names.run)}</th><th>Δ</th></tr>` +
    rows.map((x) => `<tr><td>${esc(t(`ms.${x.name}`))}</td><td class="num">${num(x.base)}</td><td class="num">${num(x.run)}</td><td class="num">${x.run > x.base ? "+" : ""}${num(x.run - x.base)}</td></tr>`).join("");
  const last = rows[rows.length - 1];
  const calls = Object.values(r.actions).reduce((a, c) => a + c, 0);
  $("#rp-result").textContent = t("replay.result", {
    run: num(last.run), base: num(last.base), pct: num(last.run / last.base - 1, { style: "percent" }),
    calls: num(calls), waits: num(r.actions.wait || 0),
    waitFrames: num(r.wait_frames), played: num(last.run - r.start_frame),
  });
  const ar = data.actionRoute;
  $("#rp-result").textContent += " " + t("replay.actions", {
    calls: num(ar.calls), frames: num(ar.total_frames), mcp: num(calls),
  });
  $("#rp-source").innerHTML = `${esc(t("label.source"))}: <code>runs/${esc(r.run_id)}/run.jsonl</code> → <code>yellow-site-data run</code> · commit <code>${esc(r.git_commit || "?")}</code>`;
}

// ---------------------------------------------------------------- benchmark
function renderBench() {
  const rows = data.bench;
  const scenarios = [...new Set(rows.map((r) => r.scenario))].sort((a, b) => SCENARIO_ORDER.indexOf(a) - SCENARIO_ORDER.indexOf(b));
  const rank = (m) => (m.startsWith("ollama:") ? 1 : 0);  // API models first, then local
  const models = [...new Set(rows.map((r) => r.model))].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  const cell = (r) => {
    if (!r) return `<td class="na">—</td>`;
    const ok = r.success;
    const cost = num(r.cost_usd, { style: "currency", currency: "USD", maximumFractionDigits: 4 });
    return `<td><button type="button" class="bench-cell ${ok ? "ok" : "fail"}" data-run="${esc(r.run_id)}">
      <b>${ok ? "✓" : "✗"} ${esc(t(`bench.stop.${r.stop}`))}</b>
      <span>${esc(t("bench.cell", { turns: num(r.turns), frames: num(r.frames), cost, invalid: num(r.invalid_actions) }))}</span></button></td>`;
  };
  $("#bench-table").innerHTML = `<tr><th>${esc(t("bench.col.scenario"))}</th>${models.map((m) => `<th>${esc(m.startsWith("ollama:") ? `${shortModel(m)} · ${t("replay.local")}` : shortModel(m))}</th>`).join("")}</tr>` +
    scenarios.map((s) => `<tr><th scope="row">${esc(scenarioLabel(s))}</th>${models.map((m) => cell(rows.find((r) => r.scenario === s && r.model === m))).join("")}</tr>`).join("");
  document.querySelectorAll(".bench-cell").forEach((b) => b.addEventListener("click", () => selectRun(b.dataset.run, true)));
  const wins = rows.filter((r) => r.success).length;
  const spent = rows.reduce((a, r) => a + r.cost_usd, 0);
  $("#bench-result").textContent = t("bench.result", { wins: num(wins), runs: num(rows.length),
    cost: num(spent, { style: "currency", currency: "USD", maximumFractionDigits: 2 }) });
  const commits = [...new Set(rows.map((r) => r.git_commit).filter(Boolean))].join(", ");
  $("#bench-source").innerHTML = `${esc(t("label.source"))}: <code>yellow-bench</code> → <code>site/data/benchmark.json</code> · commit <code>${esc(commits)}</code>`;
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
      m.custo_usd == null ? t("journal.costNotMeasured") : num(m.custo_usd, { style: "currency", currency: "USD" })].join(" · ");
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
  renderReplay();
  playReplay(false);
  renderBench();
  renderJournal();
}

async function main() {
  const [baseline, walking, sessions, mcp, ...snaps] = await Promise.all([
    getJSON("data/baseline.json"), getJSON("data/walking.json"), getJSON("data/sessions.json"),
    getJSON("data/mcp_flow.json"), ...SNAPSHOTS.map((n) => getJSON(`data/snapshots/${n}.json`)),
  ]);
  const [runs, actionRoute, bench] = await Promise.all([
    getJSON("data/runs/index.json"), getJSON("data/action_route.json"), getJSON("data/benchmark.json"),
  ]);
  const mcpEntry = runs.find((e) => e.source === "mcp");
  const mcpRun = await getJSON(`data/runs/${mcpEntry.run_id}.json`);
  data = { baseline, walking, sessions, mcp, snapshots: snaps, runs, runCache: { [mcpRun.run_id]: mcpRun },
    replay: mcpRun, mcpRun, actionRoute, bench };
  $("#lang").addEventListener("change", (e) => setLocale(e.target.value));
  $("#dec-prev").addEventListener("click", () => { playDecoder(false); stepDecoder(-1); });
  $("#dec-next").addEventListener("click", () => { playDecoder(false); stepDecoder(1); });
  $("#dec-play").addEventListener("click", () => playDecoder(!timers.dec));
  $("#flow-prev").addEventListener("click", () => { playFlow(false); stepFlow(-1); });
  $("#flow-next").addEventListener("click", () => { playFlow(false); stepFlow(1); });
  $("#flow-play").addEventListener("click", () => playFlow(!timers.flow));
  $("#rp-prev").addEventListener("click", () => { playReplay(false); stepReplay(-1); });
  $("#rp-next").addEventListener("click", () => { playReplay(false); stepReplay(1); });
  $("#rp-play").addEventListener("click", () => playReplay(!timers.rp));
  $("#rp-model").addEventListener("change", (e) => {
    const current = data.runs.find((r) => r.run_id === data.replay.run_id);
    selectRun(fillScenarios(e.target.value, runScenario(current)));
  });
  $("#rp-scen").addEventListener("change", (e) => selectRun(e.target.value));
  $("#rp-scrub").addEventListener("input", (e) => { playReplay(false); rp.i = +e.target.value; showStep(); });
  await setLocale(pickLocale());
}

main().catch((err) => {
  document.querySelector("main").insertAdjacentHTML("afterbegin", `<p style="color:#ff7a7a">${esc(err.message)}</p>`);
});
