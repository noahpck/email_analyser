// Email fields are attacker-controlled: only ever insert them with textContent.
let FLAG_AT = 40; // replaced by the server's value from /api/config
let DEMO = false;
const DEMO_LABELS_KEY = "demo-labels";
const PALETTE = ["#6ea8fe", "#f2666b", "#4fc58b", "#f0b552", "#c39bf5"];
const SVG = "http://www.w3.org/2000/svg";

const state = { emails: [], sources: new Set(), picked: new Set(), flaggedOnly: true, query: "", label: "any" };
const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  node.append(...children);
  return node;
}
function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}
const colorFor = (source) => PALETTE[[...state.sources].indexOf(source) % PALETTE.length];
const level = (score) => (score >= FLAG_AT ? "high" : score >= FLAG_AT / 2 ? "mid" : "low");
const fmtDate = (d) => (d ? new Date(d).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "–");

function toast(message, isError = false) {
  const t = el("div", { className: "toast" + (isError ? " error" : ""), textContent: message });
  $("toasts").append(t);
  setTimeout(() => t.remove(), isError ? 8000 : 4000);
}

async function load() {
  try {
    const res = await fetch("/api/emails");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.emails = await res.json();
    if (DEMO) { // labels live in this browser only
      const saved = readDemoLabels();
      for (const e of state.emails) e.label = saved[e.msg_id] || null;
    }
  } catch (err) {
    $("list").replaceChildren(el("p", { className: "muted", textContent: `Couldn't load emails: ${err.message}. Run backend/analyse.py first?` }));
    return;
  }
  const before = state.sources;
  state.sources = new Set(state.emails.map((e) => e.source).sort());
  for (const s of state.sources) if (!before.has(s)) state.picked.add(s); // keep the user's filter choices
  renderChips();
  render();
}

// --- sync status ---
let lastSyncSeen = null;
function ago(iso) {
  const s = Math.round((Date.now() - Date.parse(iso)) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 172800) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} days ago`;
}
function showStatus(st) {
  const label = $("sync-status");
  label.classList.toggle("error", !!st.last_error);
  if (st.running) label.textContent = "Syncing…";
  else if (st.last_error) label.textContent = `Sync failed: ${st.last_error}`;
  else if (st.last_sync) label.textContent = `Synced ${ago(st.last_sync)}${st.interval_minutes ? ` · every ${st.interval_minutes} min` : ""}`;
  else label.textContent = st.interval_minutes ? "Waiting for first sync…" : "Auto-sync off";
  label.title = st.last_error || "";
  $("sync-now").disabled = st.running;
}
async function pollStatus() {
  try {
    const st = await (await fetch("/api/status")).json();
    showStatus(st);
    if (st.last_sync && st.last_sync !== lastSyncSeen) {
      if (lastSyncSeen !== null && st.last_new) toast(`${st.last_new} new email${st.last_new > 1 ? "s" : ""} synced`);
      if (lastSyncSeen !== null && (st.last_new || st.last_removed)) await load();
      lastSyncSeen = st.last_sync;
    }
  } catch { /* server restarting; try again next tick */ }
}
$("sync-now").addEventListener("click", async () => {
  showStatus({ running: true });
  try {
    const res = await fetch("/api/sync", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const st = await res.json();
    showStatus(st);
    if (res.status === 409) toast("A sync is already running");
    else if (st.last_error) toast(`Sync failed: ${st.last_error}`, true);
    else { toast(st.last_new ? `${st.last_new} new email${st.last_new > 1 ? "s" : ""}` : "Up to date"); await load(); }
    lastSyncSeen = st.last_sync;
  } catch (err) {
    toast(err.message, true);
    pollStatus();
  }
});
function startSyncPolling() {
  setInterval(pollStatus, 20000);
  pollStatus();
}

function filtered() {
  const q = state.query.toLowerCase();
  return state.emails.filter((e) =>
    state.picked.has(e.source) &&
    (!state.flaggedOnly || e.flagged) &&
    (state.label === "any" || (e.label || "none") === state.label) &&
    (!q || `${e.subject} ${e.sender} ${e.from_name}`.toLowerCase().includes(q)));
}

function render() {
  const all = state.emails;
  $("m-total").textContent = all.length;
  $("m-flagged").textContent = all.filter((e) => e.flagged).length;
  $("m-avg").textContent = all.length ? (all.reduce((s, e) => s + e.score, 0) / all.length).toFixed(1) : "0";
  renderChart();
  renderList();
}

function renderChips() {
  $("sources").replaceChildren(...[...state.sources].map((source) => {
    const chip = el("button", { className: "chip", type: "button", textContent: source });
    chip.setAttribute("aria-pressed", "true");
    chip.onclick = () => {
      state.picked.has(source) ? state.picked.delete(source) : state.picked.add(source);
      chip.setAttribute("aria-pressed", state.picked.has(source));
      renderList();
    };
    return chip;
  }));
  $("legend").replaceChildren(...[...state.sources].map((s) => {
    const dot = el("i");
    dot.style.background = colorFor(s);
    return el("span", {}, dot, s);
  }));
}

function renderChart() {
  const box = $("chart");
  const points = state.emails.filter((e) => e.date).map((e) => ({ ...e, t: Date.parse(e.date) }));
  box.replaceChildren();
  if (!points.length) return;

  const W = box.clientWidth, H = box.clientHeight, m = { t: 10, r: 12, b: 26, l: 34 };
  const tMin = Math.min(...points.map((p) => p.t)), tMax = Math.max(...points.map((p) => p.t));
  const yMax = Math.max(FLAG_AT * 1.25, ...points.map((p) => p.score)) * 1.05;
  const x = (t) => m.l + ((t - tMin) / (tMax - tMin || 1)) * (W - m.l - m.r);
  const y = (v) => H - m.b - (v / yMax) * (H - m.t - m.b);

  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Score by date scatter plot" });
  const grid = svg("g", { class: "grid" }), axis = svg("g", { class: "axis" });
  const step = yMax > 150 ? 50 : 20;
  for (let v = 0; v <= yMax; v += step) {
    grid.append(svg("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }));
    const label = svg("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" });
    label.textContent = v;
    axis.append(label);
  }
  const ticks = Math.max(2, Math.min(6, Math.floor(W / 140)));
  for (let i = 0; i <= ticks; i++) {
    const t = tMin + ((tMax - tMin) * i) / ticks;
    const label = svg("text", { x: x(t), y: H - 6, "text-anchor": i === 0 ? "start" : i === ticks ? "end" : "middle" });
    label.textContent = new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" });
    axis.append(label);
  }
  root.append(grid, axis, svg("line", { class: "threshold", x1: m.l, x2: W - m.r, y1: y(FLAG_AT), y2: y(FLAG_AT) }));
  const tl = svg("text", { class: "threshold-label", x: W - m.r, y: y(FLAG_AT) - 5, "text-anchor": "end" });
  tl.textContent = `flag at ${FLAG_AT}`;
  root.append(tl);

  const tip = $("tooltip");
  for (const p of points.sort((a, b) => a.score - b.score)) {
    const c = svg("circle", { cx: x(p.t), cy: y(p.score), r: 4.5, fill: colorFor(p.source) });
    c.addEventListener("mousemove", (ev) => {
      tip.replaceChildren(el("b", { textContent: `${p.score} · ${p.source}` }), el("div", { textContent: p.subject || "(no subject)" }),
        el("div", { className: "muted", textContent: p.sender }));
      tip.hidden = false;
      tip.style.left = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8) + "px";
      tip.style.top = ev.clientY + 14 + "px";
    });
    c.addEventListener("mouseleave", () => (tip.hidden = true));
    c.addEventListener("click", () => {
      const row = document.querySelector(`details[data-id="${CSS.escape(p.msg_id)}"]`);
      if (row) { row.open = true; row.scrollIntoView({ behavior: "smooth", block: "center" }); }
    });
    root.append(c);
  }
  box.append(root);
}

function renderList() {
  const rows = filtered();
  $("list-title").textContent = `Emails (${rows.length})`;
  if (!rows.length) {
    $("list").replaceChildren(el("p", { className: "muted", textContent: "No emails match these filters." }));
    return;
  }
  $("list").replaceChildren(...rows.map(emailRow));
}

function emailRow(e) {
  const reasons = e.reasons.length
    ? e.reasons.map((r) => {
        const [pts, ...rest] = r.split(" ");
        return el("li", {}, el("span", { className: "pts", textContent: pts }), el("span", { textContent: rest.join(" ") }));
      })
    : [el("li", { className: "none", textContent: "No warning signs found." })];

  const meta = el("dl", { className: "meta" });
  for (const [k, v] of [["From", `${e.from_name} <${e.sender}>`], ["Date", fmtDate(e.date)], ["Source", e.source]]) {
    meta.append(el("dt", { textContent: k }), el("dd", { textContent: v }));
  }

  const trashBtn = el("button", { className: "btn", type: "button", textContent: "Move to trash" });
  const blockBtn = el("button", { className: "btn primary", type: "button", textContent: "Block sender & trash" });
  trashBtn.onclick = () => act(e, false, [trashBtn, blockBtn]);
  blockBtn.onclick = () => {
    if (confirm(`Block ${e.sender}? Future emails from this address will go straight to Trash.`)) act(e, true, [trashBtn, blockBtn]);
  };

  const pill = el("span", { className: "pill" });
  const labelBtns = ["safe", "scam"].map((value) => {
    const b = el("button", { className: `btn label-btn ${value}`, type: "button", textContent: value === "safe" ? "✓ Safe" : "⚠ Scam" });
    b.onclick = () => setLabel(e, e.label === value ? null : value, labelBtns, pill);
    return b;
  });
  paintLabel(e, labelBtns, pill);

  const detailBox = el("div", { className: "detail" });
  const row = el("details", {},
    el("summary", {},
      el("span", { className: `score ${level(e.score)}`, textContent: e.score }),
      el("div", { className: "summary-text" },
        el("div", { className: "subject", textContent: e.subject || "(no subject)" }),
        el("div", { className: "sender", textContent: e.from_name ? `${e.from_name} · ${e.sender}` : e.sender })),
      pill),
    el("div", { className: "body" }, meta, el("ul", { className: "reasons" }, ...reasons), detailBox,
      el("div", { className: "actions" },
        el("div", { className: "label-group", role: "group", ariaLabel: "Your verdict" }, ...labelBtns),
        el("span", { className: "spacer" }), ...(DEMO ? [] : [trashBtn, blockBtn]))));
  row.dataset.id = e.msg_id;
  row.addEventListener("toggle", () => { if (row.open && !detailBox.dataset.loaded) loadDetail(e, detailBox); });
  return row;
}

async function loadDetail(e, box) {
  box.dataset.loaded = "1";
  box.replaceChildren(el("p", { className: "muted", textContent: "Loading message…" }));
  let d;
  try {
    const res = await fetch(`/api/emails/${encodeURIComponent(e.msg_id)}/detail`);
    if (!res.ok) throw new Error(res.status === 404 ? "the .eml file is missing" : `HTTP ${res.status}`);
    d = await res.json();
  } catch (err) {
    delete box.dataset.loaded;
    box.replaceChildren(el("p", { className: "muted", textContent: `Couldn't load message: ${err.message}` }));
    return;
  }
  const parts = [];

  // authentication
  const auth = el("div", { className: "auth" });
  if (d.auth) {
    for (const k of ["spf", "dkim", "dmarc"]) {
      const v = d.auth[k];
      const cls = v === "pass" ? "ok" : v === "none" ? "neutral" : "bad";
      auth.append(el("span", { className: `auth-item ${cls}`, textContent: `${k.toUpperCase()} ${v}` }));
    }
  } else {
    auth.append(el("span", { className: "auth-item neutral", textContent: "No Gmail auth results (draft or self-sent)" }));
  }
  parts.push(auth);

  const extra = el("dl", { className: "meta" });
  for (const [k, v] of [["Reply-To", d.reply_to], ["Return-Path", d.return_path], ["Attachments", d.attachments.join(", ")]]) {
    if (v) extra.append(el("dt", { textContent: k }), el("dd", { textContent: v }));
  }
  if (extra.children.length) parts.push(extra);

  // message body (plain text only, never rendered as HTML)
  parts.push(el("h3", { textContent: "Message" }),
    el("pre", { className: "message", textContent: d.body || "(no text content)" }));

  // links
  if (d.links.length) {
    const warned = d.links.filter((l) => l.warning).length;
    parts.push(el("h3", { textContent: `Links (${d.link_count}${warned ? ` · ${warned} suspicious` : ""})` }));
    const ul = el("ul", { className: "links" });
    for (const l of [...d.links].sort((a, b) => !!b.warning - !!a.warning)) {
      const li = el("li", { className: l.warning ? "warn" : "" },
        el("div", { className: "link-head" },
          l.warning ? el("span", { className: "link-warn", textContent: `⚠ ${l.warning}` }) : "",
          el("span", { className: "link-host", textContent: l.host })),
        l.text && l.text !== l.href ? el("div", { className: "link-text", textContent: `Shown as: ${l.text}` }) : "",
        el("div", { className: "link-url", textContent: l.href }));
      ul.append(li);
    }
    parts.push(ul);
    if (d.link_count > d.links.length) parts.push(el("p", { className: "muted", textContent: `…and ${d.link_count - d.links.length} more` }));
  }
  box.replaceChildren(...parts);
}

function paintLabel(e, buttons, pill) {
  buttons.forEach((b) => b.setAttribute("aria-pressed", b.classList.contains(e.label || "-")));
  pill.className = `pill ${e.label || ""}`;
  pill.textContent = e.label === "safe" ? "Safe" : e.label === "scam" ? "Scam" : "";
  pill.hidden = !e.label;
}

function readDemoLabels() {
  try { return JSON.parse(localStorage.getItem(DEMO_LABELS_KEY)) || {}; } catch { return {}; }
}

async function setLabel(e, label, buttons, pill) {
  const previous = e.label;
  e.label = label;
  paintLabel(e, buttons, pill); // optimistic; reverted on failure
  if (DEMO) {
    const saved = readDemoLabels();
    if (label) saved[e.msg_id] = label; else delete saved[e.msg_id];
    try { localStorage.setItem(DEMO_LABELS_KEY, JSON.stringify(saved)); } catch { /* private mode: keep in memory */ }
    return;
  }
  try {
    await postJSON(`/api/emails/${encodeURIComponent(e.msg_id)}/label`, { label });
  } catch (err) {
    e.label = previous;
    paintLabel(e, buttons, pill);
    toast(`Couldn't save label: ${err.message}`, true);
  }
}

async function act(e, block, buttons) {
  buttons.forEach((b) => (b.disabled = true));
  try {
    await postJSON(`/api/emails/${encodeURIComponent(e.msg_id)}/trash`, { block });
    state.emails = state.emails.filter((x) => x.msg_id !== e.msg_id);
    render();
    toast(block ? `Moved to trash and blocked ${e.sender}` : "Moved to trash");
  } catch (err) {
    buttons.forEach((b) => (b.disabled = false));
    toast(err.message, true);
  }
}

// --- history & blocked senders ---
const ACTION_LABELS = { trashed: "Trashed", blocked: "Blocked + trashed", removed_in_gmail: "Removed in Gmail" };

function showTab(name) {
  for (const t of ["emails", "history"]) {
    $(`tab-${t}`).setAttribute("aria-selected", t === name);
    $(`view-${t}`).hidden = t !== name;
  }
  if (name === "history") loadHistory();
  else renderChart(); // the chart can't measure itself while hidden
}

async function getJSON(url) {
  const res = await fetch(url);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}
async function postJSON(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function loadHistory() {
  loadBlocked();
  const box = $("history");
  let rows;
  try { rows = await getJSON("/api/history"); } catch (err) {
    box.replaceChildren(el("p", { className: "muted", textContent: `Couldn't load history: ${err.message}` }));
    return;
  }
  if (!rows.length) { box.replaceChildren(el("p", { className: "muted", textContent: "Nothing trashed or blocked yet." })); return; }
  box.replaceChildren(...rows.map((h) => {
    const btn = el("button", { className: "btn", type: "button", textContent: h.action === "blocked" ? "Undo (restore + unblock)" : "Restore" });
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        const r = await postJSON(`/api/emails/${encodeURIComponent(h.msg_id)}/undo`, {});
        toast(r.unblocked ? `Restored and unblocked ${r.sender}` : "Restored to Gmail");
        await Promise.all([loadHistory(), load()]);
      } catch (err) { btn.disabled = false; toast(err.message, true); }
    };
    return el("div", { className: "row" },
      el("span", { className: `badge ${h.action}`, textContent: ACTION_LABELS[h.action] || h.action }),
      el("div", { className: "row-main" },
        el("div", { className: "subject", textContent: h.subject || "(no subject)" }),
        el("div", { className: "sender", textContent: `${h.sender || "unknown sender"} · ${h.at ? ago(h.at.replace(" ", "T") + "Z") : ""}` })),
      btn);
  }));
}

async function loadBlocked() {
  const box = $("blocked");
  let senders;
  try { senders = await getJSON("/api/blocked"); } catch (err) {
    box.replaceChildren(el("p", { className: "muted", textContent: `Couldn't load blocked senders: ${err.message}` }));
    return;
  }
  if (!senders.length) { box.replaceChildren(el("p", { className: "muted", textContent: "No blocked senders." })); return; }
  box.replaceChildren(...senders.map((sender) => {
    const btn = el("button", { className: "btn", type: "button", textContent: "Unblock" });
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await postJSON("/api/blocked/unblock", { sender });
        toast(`Unblocked ${sender}. Already-trashed emails stay in Trash.`);
        loadBlocked();
      } catch (err) { btn.disabled = false; toast(err.message, true); }
    };
    return el("div", { className: "row" }, el("div", { className: "row-main subject", textContent: sender }), btn);
  }));
}

$("tab-emails").addEventListener("click", () => showTab("emails"));
$("tab-history").addEventListener("click", () => showTab("history"));

$("search").addEventListener("input", (ev) => { state.query = ev.target.value; renderList(); });
$("label-filter").addEventListener("change", (ev) => { state.label = ev.target.value; renderList(); });
$("flagged-only").addEventListener("change", (ev) => { state.flaggedOnly = ev.target.checked; renderList(); });
let resizeTimer;
addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderChart, 150); });
async function init() {
  try {
    const cfg = await getJSON("/api/config");
    FLAG_AT = cfg.flag_at;
    DEMO = cfg.demo;
    if (DEMO) {
      $("demo-banner").hidden = false;
      $("sync-box").hidden = true;
      document.querySelector(".tabs").hidden = true; // only one tab in the demo
      if (cfg.repo_url) {
        const a = $("demo-repo");
        a.href = cfg.repo_url;
        a.hidden = false;
      }
    } else if (cfg.sync) {
      startSyncPolling();
    } else {
      $("sync-status").textContent = "Auto-sync off";
    }
  } catch { startSyncPolling(); /* older server: assume defaults */ }
  load();
}
init();
