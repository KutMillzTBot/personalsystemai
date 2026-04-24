/* app.js - Supervisor Command Center (Deriv + MT5 bridge sync) */
const DEFAULT_BRIDGE = "http://127.0.0.1:5050";
const POLL = 5000;
const API_FAILURE_LIMIT = 3;
const AUTO_RECONNECT_MS = 10000;
const HEAVY_REFRESH_MS = 15000;

const STORAGE = {
  bridge: "supervisor_bridge_url",
  symbol: "supervisor_symbol",
  autoSymbol: "supervisor_auto_symbol_sync",
  brokerMode: "supervisor_broker_mode",
  derivLayoutUrl: "supervisor_deriv_layout_url",
  chartTemplate: "supervisor_chart_template_v1",
};

function readBridgeMetaPreset() {
  const meta = document.querySelector('meta[name="default-bridge"]');
  return String(meta?.getAttribute("content") || "").trim();
}

function inferBridgeFromHost() {
  const host = String(window.location.hostname || "").toLowerCase();
  const protocol = String(window.location.protocol || "https:");
  if (host === "127.0.0.1" || host === "localhost") return DEFAULT_BRIDGE;
  if (host.endsWith(".trycloudflare.com")) return `${protocol}//${window.location.host}`;
  return "";
}

function resolveInitialBridge() {
  return (
    params.get("bridge") ||
    window.BRIDGE_URL ||
    localStorage.getItem(STORAGE.bridge) ||
    readBridgeMetaPreset() ||
    inferBridgeFromHost() ||
    DEFAULT_BRIDGE
  );
}

const params = new URLSearchParams(window.location.search);
let BRIDGE = safeNormalizeBridge(
  resolveInitialBridge()
);

let currentSymbol = (localStorage.getItem(STORAGE.symbol) || "V75").toUpperCase();
let autoSymbolSync = localStorage.getItem(STORAGE.autoSymbol) !== "0";
let brokerMode = String(localStorage.getItem(STORAGE.brokerMode) || "auto").toLowerCase();
let derivLayoutUrl = String(localStorage.getItem(STORAGE.derivLayoutUrl) || "").trim();
if (!["auto", "mt5", "deriv"].includes(brokerMode)) brokerMode = "auto";

let logLines = [];
let isConnected = false;
let userDisconnected = false;
let lastSyncTime = null;
let lastPrice = null;
let manualSide = "BUY";
let manualOrderType = "BUY_MARKET";
let manualDragTarget = "entry";
let consecutiveApiFailures = 0;
let refreshInFlight = false;
let refreshQueued = false;
let lastHeavyRefreshAt = 0;
let manualSymbolLockUntil = 0;
let latestMtSymbol = "";

const MODEL_EXPLAIN = {
  candle_patterns: "Reads candle structure and reversal/continuation formations to improve entry timing.",
  correlation: "Checks cross-market alignment so we avoid trades when correlated symbols disagree.",
  divergence: "Looks for momentum/price disagreement to catch weakening moves before reversal.",
  elliott_wave: "Tracks wave phases to estimate trend continuation vs correction probability.",
  fibonacci: "Finds retracement/extension reaction zones for higher-probability entries and targets.",
  liquidity_sweep: "Detects stop-hunts/liquidity grabs so entries avoid obvious trap candles.",
  mtf_confluence: "Confirms lower timeframe setup against higher timeframe direction.",
  news_volatility: "Adjusts confidence around high-impact news and volatility regime shifts.",
  regime: "Detects trending vs ranging market regime and adapts strategy weighting.",
  rsi_trend: "Uses RSI behavior with trend context to filter weak momentum entries.",
  sessions: "Scores session timing (London/NY/Asia) because liquidity profile changes edge.",
  smart_money: "Tracks market structure and institutional footprint behavior for directional bias.",
  supply_demand: "Uses supply/demand zones to define reaction areas and risk placement.",
  volume_orderflow: "Reads participation/flow pressure to confirm real intent behind moves.",
  wyckoff: "Classifies accumulation/distribution behavior for phase-based directional bias.",
  ensemble_head: "Final decision layer that combines all model outputs with dynamic weighting.",
};

const $ = id => document.getElementById(id);
const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
const html = (id, v) => { const e = $(id); if (e) e.innerHTML = v; };

const fmtUsd = v => `$${Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmtPct = v => `${(Number(v || 0) * 100).toFixed(1)}%`;
const cls = v => Number(v || 0) >= 0 ? "pos" : "neg";
const sgn = v => Number(v || 0) >= 0 ? "+" : "";

const DERIV_SYMBOL_MAP = {
  EURUSD: "frxEURUSD",
  GBPUSD: "frxGBPUSD",
  USDCHF: "frxUSDCHF",
  NZDUSD: "frxNZDUSD",
  EURJPY: "frxEURJPY",
  EURGBP: "frxEURGBP",
  EURAUD: "frxEURAUD",
  GBPCHF: "frxGBPCHF",
  USDJPY: "frxUSDJPY",
  GBPJPY: "frxGBPJPY",
  AUDUSD: "frxAUDUSD",
  USDCAD: "frxUSDCAD",
  XAUUSD: "frxXAUUSD",
  XAGUSD: "frxXAGUSD",
  BTCUSD: "cryBTCUSD",
  ETHUSD: "cryETHUSD",
  LTCUSD: "cryLTCUSD",
  XRPUSD: "cryXRPUSD",
  SOLUSD: "crySOLUSD",
  V10: "R_10",
  V25: "R_25",
  V50: "R_50",
  V75: "R_75",
  V100: "R_100",
  CRASH300: "CRASH300",
  BOOM300: "BOOM300",
  CRASH500: "CRASH500",
  BOOM500: "BOOM500",
  CRASH1000: "CRASH1000",
  BOOM1000: "BOOM1000",
};

function safeNormalizeBridge(raw) {
  try { return normalizeBridgeURL(raw); }
  catch { return DEFAULT_BRIDGE; }
}

function normalizeBridgeURL(raw) {
  let v = String(raw || "").trim();
  if (!v) throw new Error("empty bridge url");
  if (!/^https?:\/\//i.test(v)) v = "http://" + v;
  const u = new URL(v);
  return `${u.protocol}//${u.host}`;
}

function bridgeCandidates(raw) {
  const out = [];
  const seen = new Set();
  const push = value => {
    try {
      const normalized = normalizeBridgeURL(value);
      if (!seen.has(normalized)) {
        seen.add(normalized);
        out.push(normalized);
      }
    } catch {}
  };

  push(raw);
  push(BRIDGE);
  push(DEFAULT_BRIDGE);

  try {
    const base = new URL(normalizeBridgeURL(raw || BRIDGE || DEFAULT_BRIDGE));
    ["5050", "5058"].forEach(port => {
      const candidate = `${base.protocol}//${base.hostname}:${port}`;
      push(candidate);
    });
  } catch {}

  return out;
}

function setBridge(url, { persist = true, syncInput = true } = {}) {
  BRIDGE = safeNormalizeBridge(url);
  if (persist) localStorage.setItem(STORAGE.bridge, BRIDGE);
  set("bridge-url", BRIDGE);
  if (syncInput && $("settings-bridge-url")) $("settings-bridge-url").value = BRIDGE;
}

function addLog(text, type = "info") {
  const now = new Date().toTimeString().slice(0, 8);
  logLines.push({ now, text, type });
  if (logLines.length > 250) logLines = logLines.slice(-250);
  const t = $("log-terminal");
  if (!t) return;
  t.innerHTML = logLines.slice(-90).map(l =>
    `<div class="log-entry"><span class="log-time">${l.now}</span><span class="log-text ${l.type}">${l.text}</span></div>`
  ).join("");
  t.scrollTop = t.scrollHeight;
}

function setConnectionState(connected, backendStateText) {
  isConnected = !!connected;
  if (connected) consecutiveApiFailures = 0;

  const dot = document.querySelector(".nav-dot");
  if (dot) {
    dot.style.background = connected ? "var(--green)" : "var(--red)";
    dot.style.boxShadow = connected ? "0 0 10px var(--green)" : "0 0 10px var(--red)";
  }

  set("settings-connect-state", connected ? "Connected" : "Disconnected");
  set("settings-backend-state", backendStateText || (connected ? "Online" : "Offline"));

  const btn = $("settings-connect-toggle");
  if (btn) {
    btn.textContent = connected ? "Disconnect" : "Connect";
    btn.classList.remove("btn-primary", "btn-danger");
    btn.classList.add(connected ? "btn-danger" : "btn-primary");
  }

  if (!connected) {
    set("status-engine", "Disconnected");
    set("settings-last-sync", "Disconnected");
    set("settings-mt-link", "Waiting");
  }
}

function openSection(sectionId) {
  document.querySelectorAll(".sidebar-item").forEach(i => i.classList.remove("active"));
  document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
  const item = document.querySelector(`.sidebar-item[data-section="${sectionId}"]`);
  if (item) item.classList.add("active");
  $(sectionId)?.classList.add("active");
  if (sectionId === "section-forexsmartbot") syncForexSmartBotSection();
}

function parseSignalText(payload) {
  const raw = payload?.signal ?? payload?.action_text ?? payload?.action;
  if (typeof raw === "number") {
    if (raw > 0) return "BUY";
    if (raw < 0) return "SELL";
    return "HOLD";
  }
  const s = String(raw || "HOLD").toUpperCase();
  if (s.includes("STRONG BUY")) return "STRONG BUY";
  if (s.includes("STRONG SELL")) return "STRONG SELL";
  if (s.includes("BUY")) return "BUY";
  if (s.includes("SELL")) return "SELL";
  return "HOLD";
}

function badge(sig) {
  const s = parseSignalText({ signal: sig });
  if (s.includes("STRONG BUY")) return '<span class="badge buy">STRONG BUY</span>';
  if (s.includes("BUY")) return '<span class="badge buy">BUY</span>';
  if (s.includes("STRONG SELL")) return '<span class="badge sell">STRONG SELL</span>';
  if (s.includes("SELL")) return '<span class="badge sell">SELL</span>';
  return '<span class="badge hold">HOLD</span>';
}

function updateHeroGlow(signalText) {
  const card = document.querySelector(".hero-card");
  if (!card) return;
  card.classList.remove("buy-glow", "sell-glow", "hold-glow");
  const s = parseSignalText({ signal: signalText });
  if (s.includes("BUY")) card.classList.add("buy-glow");
  else if (s.includes("SELL")) card.classList.add("sell-glow");
  else card.classList.add("hold-glow");
}

function buildDerivChartUrl(symbol) {
  const mapped = DERIV_SYMBOL_MAP[symbol] || symbol;
  const base = derivLayoutUrl && derivLayoutUrl.includes("charts.deriv.com")
    ? derivLayoutUrl
    : "https://charts.deriv.com/deriv";

  const u = new URL(base);
  if (!u.pathname || u.pathname === "/") u.pathname = "/deriv";
  u.searchParams.set("symbol", mapped);
  return u.toString();
}

function isLocalStaticHost() {
  const host = String(window.location.hostname || "").toLowerCase();
  return host === "127.0.0.1" || host === "localhost";
}

function getSupervisorEntryPath() {
  const path = String(window.location.pathname || "").toLowerCase();
  if (path.endsWith("/index.html") || path === "/" || path.endsWith("/")) return "./index.html";
  return "./command_center.html";
}

function getForexSmartBotStandaloneUrl() {
  if (isLocalStaticHost()) {
    return `http://127.0.0.1:8080/forexsmartbot_dashboard.html?bridge=${encodeURIComponent(BRIDGE)}`;
  }
  return `./ForexSmartBot/forexsmartbot_dashboard.html?bridge=${encodeURIComponent(BRIDGE)}`;
}

function renderDerivChart(symbol) {
  const frame = $("deriv-chart-frame");
  if (!frame) return;
  const src = buildDerivChartUrl(symbol);
  if (frame.src !== src) frame.src = src;
}

function applySymbol(symbol, { fromBackend = false, persist = true } = {}) {
  const s = String(symbol || "").trim().toUpperCase();
  if (!s) return;
  if (!fromBackend) manualSymbolLockUntil = Date.now() + 60000;
  currentSymbol = s;

  const sel = $("nav-symbol-select");
  if (sel) {
    const opt = [...sel.options].find(o => o.value.toUpperCase() === s);
    if (opt) sel.value = opt.value;
  }

  if (persist) localStorage.setItem(STORAGE.symbol, currentSymbol);
  set("signal-symbol", currentSymbol);
  set("status-symbol", currentSymbol);
  set("settings-mt-symbol", currentSymbol);
  renderDerivChart(currentSymbol);
  renderWatchlist(window.__lastMtWatchlist || []);

  if (!fromBackend && isConnected) {
    post("/trading/symbol", { symbol: currentSymbol });
  }
}

function manualTickSize() {
  if (!lastPrice || !Number.isFinite(lastPrice)) return 0.0001;
  if (lastPrice > 5000) return 1;
  if (lastPrice > 1000) return 0.5;
  if (lastPrice > 100) return 0.05;
  if (lastPrice > 10) return 0.01;
  if (lastPrice > 1) return 0.001;
  return 0.0001;
}

function formatPrice(v) {
  const n = Number(v || 0);
  if (!Number.isFinite(n)) return "0.00000";
  if (Math.abs(n) >= 1000) return n.toFixed(2);
  if (Math.abs(n) >= 1) return n.toFixed(5);
  return n.toFixed(6);
}

function currentManualSideFromType(type = manualOrderType) {
  return String(type || "").toUpperCase().startsWith("SELL") ? "SELL" : "BUY";
}

function orderTypeUsesLimitPrice(type = manualOrderType) {
  return String(type || "").toUpperCase().includes("STOP_LIMIT");
}

function orderTypeNeedsPendingEntry(type = manualOrderType) {
  const t = String(type || "").toUpperCase();
  return t.includes("LIMIT") || t.includes("STOP");
}

function updateManualModeUI() {
  manualSide = currentManualSideFromType(manualOrderType);
  if ($("manual-side-label")) $("manual-side-label").value = manualSide;
  const limitWrap = $("manual-limit-price-wrap");
  if (limitWrap) limitWrap.classList.toggle("hidden", !orderTypeUsesLimitPrice(manualOrderType));
  set("manual-drag-help", orderTypeNeedsPendingEntry(manualOrderType)
    ? `${manualOrderType.replaceAll("_", " ")}: drag Entry first, then SL / TP.`
    : `${manualSide} market: entry stays at live price while you drag SL / TP around it.`);
  ["drag-entry-line", "drag-sl-line", "drag-tp-line"].forEach(id => $(id)?.classList.remove("is-armed"));
  $(`drag-${manualDragTarget}-line`)?.classList.add("is-armed");
}

function setManualLevels(entry, sl, tp) {
  if (!Number.isFinite(entry) || entry <= 0) return;
  lastPrice = entry;
  if ($("manual-entry")) $("manual-entry").value = formatPrice(entry);
  if ($("manual-sl")) $("manual-sl").value = formatPrice(sl);
  if ($("manual-tp")) $("manual-tp").value = formatPrice(tp);
}

function seedManualLevels(side = manualSide) {
  if (!Number.isFinite(lastPrice) || lastPrice <= 0) return;
  const step = manualTickSize() * 20;
  if (side === "BUY") {
    setManualLevels(lastPrice, lastPrice - step, lastPrice + step * 1.6);
  } else {
    setManualLevels(lastPrice, lastPrice + step, lastPrice - step * 1.6);
  }
  syncDragLinesFromInputs();
}

function syncDragLinesFromInputs() {
  const board = $("manual-drag-board");
  if (!board || !Number.isFinite(lastPrice) || lastPrice <= 0) return;
  const h = board.clientHeight || 260;
  const span = Math.max(lastPrice * 0.02, manualTickSize() * 400);
  const mid = h / 2;
  const setY = (id, price) => {
    const line = $(id);
    if (!line) return;
    const y = mid - ((price - lastPrice) / span) * h;
    line.style.top = `${Math.max(10, Math.min(h - 10, y))}px`;
  };
  const entryRef = Number($("manual-entry")?.value || lastPrice);
  setY("drag-entry-line", entryRef);
  setY("drag-sl-line", Number($("manual-sl")?.value || entryRef));
  setY("drag-tp-line", Number($("manual-tp")?.value || entryRef));
}

function syncInputsFromDragLines() {
  const board = $("manual-drag-board");
  if (!board || !Number.isFinite(lastPrice) || lastPrice <= 0) return;
  const h = board.clientHeight || 260;
  const span = Math.max(lastPrice * 0.02, manualTickSize() * 400);
  const mid = h / 2;
  const priceFromTop = top => lastPrice + ((mid - top) / h) * span;
  const entryTop = parseFloat(($("drag-entry-line")?.style.top || "").replace("px", "")) || (h / 2);
  const slTop = parseFloat(($("drag-sl-line")?.style.top || "").replace("px", "")) || (h * 0.7);
  const tpTop = parseFloat(($("drag-tp-line")?.style.top || "").replace("px", "")) || (h * 0.3);
  const entryPrice = orderTypeNeedsPendingEntry(manualOrderType) ? priceFromTop(entryTop) : lastPrice;
  if ($("manual-side-label")) $("manual-side-label").value = manualSide;
  if ($("manual-entry")) $("manual-entry").value = formatPrice(entryPrice);
  if ($("manual-sl")) $("manual-sl").value = formatPrice(priceFromTop(slTop));
  if ($("manual-tp")) $("manual-tp").value = formatPrice(priceFromTop(tpTop));
  if (orderTypeUsesLimitPrice(manualOrderType) && $("manual-limit-price")) {
    const limitOffset = manualSide === "BUY" ? -manualTickSize() * 10 : manualTickSize() * 10;
    $("manual-limit-price").value = formatPrice(entryPrice + limitOffset);
  }
}

function setupDragLine(id) {
  const line = $(id);
  const board = $("manual-drag-board");
  if (!line || !board) return;
  let dragging = false;

  const move = ev => {
    if (!dragging) return;
    if (manualDragTarget !== id.replace("drag-", "").replace("-line", "")) return;
    const rect = board.getBoundingClientRect();
    const y = Math.max(10, Math.min(rect.height - 10, ev.clientY - rect.top));
    line.style.top = `${y}px`;
    syncInputsFromDragLines();
  };
  const up = () => { dragging = false; };

  line.addEventListener("pointerdown", ev => {
    dragging = true;
    line.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });
  line.addEventListener("pointermove", move);
  line.addEventListener("pointerup", up);
  line.addEventListener("pointercancel", up);
}

async function placeManualTrade(side) {
  if (!isConnected) {
    addLog("Connect backend before placing manual trades", "warn");
    openSection("section-settings");
    return;
  }

  const entry = Number($("manual-entry")?.value || lastPrice || 0);
  const limitPrice = Number($("manual-limit-price")?.value || 0);
  const sl = Number($("manual-sl")?.value || 0);
  const tp = Number($("manual-tp")?.value || 0);
  const lot = Number($("manual-lot")?.value || 0.01);
  const sideNorm = String(side || manualSide).toUpperCase();
  const orderType = String($("manual-order-type")?.value || manualOrderType || `${sideNorm}_MARKET`).toUpperCase();
  const useSl = !!$("manual-use-sl")?.checked;
  const useTp = !!$("manual-use-tp")?.checked;
  const trailingStart = Number($("manual-trailing-start")?.value || 0.5);
  const trailingStep = Number($("manual-trailing-step")?.value || 0.5);

  const riskWarning = "Manual trading is at your own risk. Rule #1: Risk management first. Continue?";
  if (!window.confirm(riskWarning)) return;

  const res = await post("/trades/manual", {
    symbol: currentSymbol,
    type: sideNorm,
    side: sideNorm,
    order_type: orderType,
    lot,
    entry,
    limit_price: limitPrice,
    sl,
    tp,
    use_sl: useSl,
    use_tp: useTp,
    trailing_start_rr: trailingStart,
    trailing_step_rr: trailingStep,
    note: `Manual ${orderType}`,
  });

  if (!res || res.status !== "ok") {
    addLog(`Manual order rejected. ${res?.error || "Check entry / SL / TP placement."}`, "error");
    return;
  }

  addLog(`${orderType} submitted on ${currentSymbol} ticket=${res.ticket}${res.queued_mt ? " (queued to MT5)" : ""}`, "trade");
  await refreshAll();
}

function showModelInfo(name) {
  const modal = $("model-info-modal");
  if (!modal) return;
  set("model-info-title", name);
  set("model-info-body", MODEL_EXPLAIN[name] || "This model contributes to the ensemble decision and risk-adjusted confidence.");
  modal.classList.add("open");
}

function renderWatchlist(symbols = []) {
  window.__lastMtWatchlist = Array.isArray(symbols) ? symbols.slice() : [];
  const host = $("market-watchlist");
  const nav = $("nav-symbol-select");
  if (nav) {
    window.__lastMtWatchlist.forEach(symbol => {
      const sym = String(symbol || "").toUpperCase();
      if (!sym) return;
      const exists = [...nav.options].some(opt => String(opt.value || "").toUpperCase() === sym);
      if (!exists) {
        nav.appendChild(new Option(sym, sym));
      }
    });
  }
  if (!host) return;
  const items = window.__lastMtWatchlist.filter(Boolean);
  if (!items.length) {
    host.innerHTML = '<div class="chart-note">No MT5 Market Watch symbols received yet.</div>';
    return;
  }
  host.innerHTML = items.map(symbol => {
    const sym = String(symbol || "").toUpperCase();
    const active = sym === currentSymbol ? "active" : "";
    const source = sym === latestMtSymbol ? "MT chart" : "Watchlist";
    return `<button class="watchlist-chip ${active}" type="button" data-watch-symbol="${sym}">${sym}<small>${source}</small></button>`;
  }).join("");
}

async function fetchJson(url, opts = {}) {
  const controller = new AbortController();
  const timeout = opts.timeout || 6500;
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const res = await fetch(url, {
      method: opts.method || "GET",
      headers: opts.headers || { "Content-Type": "application/json" },
      body: opts.body,
      cache: "no-store",
      signal: controller.signal,
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function api(ep) {
  if (!isConnected) return null;
  try {
    const data = await fetchJson(BRIDGE + ep);
    consecutiveApiFailures = 0;
    return data;
  } catch (err) {
    consecutiveApiFailures += 1;
    set("settings-backend-state", `Degraded (${consecutiveApiFailures}/${API_FAILURE_LIMIT})`);
    addLog(`Backend request failed for ${ep}: ${err.message || "network"}`, consecutiveApiFailures >= API_FAILURE_LIMIT ? "error" : "warn");
    if (consecutiveApiFailures >= API_FAILURE_LIMIT) {
      setConnectionState(false, `Reachability issue (${err.message || "network"})`);
      if (!userDisconnected) {
        setTimeout(() => connectBridge({ silent: true }), 1500);
      }
    }
    return null;
  }
}

async function post(ep, body = {}, { allowDisconnected = false } = {}) {
  if (!isConnected && !allowDisconnected) return null;
  try {
    const data = await fetchJson(BRIDGE + ep, {
      method: "POST",
      body: JSON.stringify(body || {}),
    });
    consecutiveApiFailures = 0;
    return data;
  } catch (err) {
    if (isConnected) {
      consecutiveApiFailures += 1;
      set("settings-backend-state", `Degraded (${consecutiveApiFailures}/${API_FAILURE_LIMIT})`);
      addLog(`POST failed for ${ep}: ${err.message || "network"}`, consecutiveApiFailures >= API_FAILURE_LIMIT ? "error" : "warn");
      if (consecutiveApiFailures >= API_FAILURE_LIMIT) {
        setConnectionState(false, `POST failed (${err.message || "network"})`);
        if (!userDisconnected) {
          setTimeout(() => connectBridge({ silent: true }), 1500);
        }
      }
    }
    return null;
  }
}

async function probeBridge(url) {
  const base = safeNormalizeBridge(url);
  const [ping, status] = await Promise.all([
    fetchJson(base + "/ping", { timeout: 5000 }),
    fetchJson(base + "/status", { timeout: 7000 }),
  ]);
  return { ping, status, base };
}

async function connectBridge({ silent = false } = {}) {
  userDisconnected = false;
  const raw = $("settings-bridge-url")?.value || BRIDGE;
  let base;

  try {
    base = normalizeBridgeURL(raw);
  } catch {
    setConnectionState(false, "Invalid backend URL");
    if (!silent) addLog("Invalid backend URL", "error");
    return false;
  }

  set("settings-backend-state", "Checking...");

  let lastErr = null;
  for (const candidate of bridgeCandidates(base)) {
    try {
      const info = await probeBridge(candidate);
      setBridge(info.base, { persist: true, syncInput: true });
      setConnectionState(true, "Online");
      if (!silent) addLog(`Connected to ${info.base}`, "success");

      await post("/mt/connect", { enabled: true, broker_mode: brokerMode });

      const backendSymbol = String(info.status?.symbol || "").toUpperCase();
      if (backendSymbol) applySymbol(backendSymbol, { fromBackend: true, persist: true });

      await refreshAll();
      return true;
    } catch (err) {
      lastErr = err;
    }
  }
  setBridge(base, { persist: true, syncInput: true });
  setConnectionState(false, `Offline (${lastErr?.message || "network"})`);
  if (!silent) addLog(`Failed to connect: ${lastErr?.message || "network"}`, "error");
  return false;
}

function disconnectBridge() {
  userDisconnected = true;
  if (isConnected) {
    post("/mt/connect", { enabled: false, broker_mode: brokerMode });
  }
  setConnectionState(false, "Disconnected by user");
  addLog("Disconnected from backend", "warn");
}

function saveChartTemplate() {
  const template = {
    version: 1,
    bridge: BRIDGE,
    symbol: currentSymbol,
    autoSymbolSync,
    brokerMode,
    derivLayoutUrl,
    updatedAt: new Date().toISOString(),
  };
  localStorage.setItem(STORAGE.chartTemplate, JSON.stringify(template));
  return template;
}

function applyChartTemplate(template, { persist = true } = {}) {
  if (!template || typeof template !== "object") return;

  if (template.bridge) setBridge(template.bridge, { persist: true, syncInput: true });

  if (typeof template.autoSymbolSync === "boolean") {
    autoSymbolSync = template.autoSymbolSync;
    localStorage.setItem(STORAGE.autoSymbol, autoSymbolSync ? "1" : "0");
    if ($("settings-auto-symbol")) $("settings-auto-symbol").checked = autoSymbolSync;
  }

  if (typeof template.brokerMode === "string") {
    brokerMode = template.brokerMode.toLowerCase();
    localStorage.setItem(STORAGE.brokerMode, brokerMode);
    if ($("settings-broker-select")) $("settings-broker-select").value = brokerMode;
  }

  if (typeof template.derivLayoutUrl === "string") {
    derivLayoutUrl = template.derivLayoutUrl.trim();
    localStorage.setItem(STORAGE.derivLayoutUrl, derivLayoutUrl);
    if ($("settings-deriv-layout-url")) $("settings-deriv-layout-url").value = derivLayoutUrl;
  }

  if (template.symbol) applySymbol(template.symbol, { fromBackend: false, persist: true });
  renderDerivChart(currentSymbol);

  if (persist) localStorage.setItem(STORAGE.chartTemplate, JSON.stringify(template));
}

function downloadTemplateFile() {
  const tpl = saveChartTemplate();
  const blob = new Blob([JSON.stringify(tpl, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `supervisor_chart_template_${Date.now()}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function uploadTemplateFile(file) {
  if (!file) return;
  const text = await file.text();
  const parsed = JSON.parse(text);
  applyChartTemplate(parsed, { persist: true });
  addLog("Chart template uploaded", "success");
}

async function loadStatus() {
  const [st, acc, health] = await Promise.all([
    api("/status"),
    api("/account"),
    api("/health"),
  ]);

  if (!st) return;

  set("status-engine", st.running ? "Running" : "Stopped");
  set("status-mode", String(st.mode || "?").toUpperCase());
  set("status-uptime", st.uptime || "-");

  latestMtSymbol = String(st.mt_symbol || health?.mt_symbol || "").toUpperCase();
  const backendSymbol = String(st.selected_symbol || st.symbol || "").toUpperCase();
  const watchlist = st.mt_watchlist || health?.mt_watchlist || [];
  renderWatchlist(watchlist);

  if (backendSymbol) {
    if (autoSymbolSync && Date.now() > manualSymbolLockUntil && latestMtSymbol && latestMtSymbol !== currentSymbol) {
      applySymbol(latestMtSymbol, { fromBackend: true, persist: true });
      addLog(`Auto-synced chart symbol from MT5: ${latestMtSymbol}`, "info");
    } else if (autoSymbolSync && !latestMtSymbol && backendSymbol !== currentSymbol && Date.now() > manualSymbolLockUntil) {
      applySymbol(backendSymbol, { fromBackend: true, persist: true });
      addLog(`Auto-synced symbol from backend: ${backendSymbol}`, "info");
    }
    set("status-symbol", backendSymbol);
    set("settings-mt-symbol", latestMtSymbol || backendSymbol);
  } else {
    set("status-symbol", currentSymbol);
  }

  if (health) {
    const ingestCounts = health.ingest_counts || {};
    const countForSymbol = Number(ingestCounts[currentSymbol] || 0);
    set("settings-ingest-bars", String(countForSymbol));
    set("settings-ingest-time", health.last_symbol_time || "-");
    if (st.broker_mode && $("settings-broker-select")) {
      $("settings-broker-select").value = st.broker_mode;
    }
    const detected = st.broker_detected || st.account_broker || "";
    if (st.mt_connected || health.last_symbol_time) {
      set("settings-mt-link", detected ? `Attached (${detected})` : "Attached");
    } else {
      set("settings-mt-link", "Waiting");
    }
  }

  if (acc) {
    const balance = Number(acc.balance || 0);
    const equity = Number(acc.equity || 0);
    const fl = equity - balance;

    ["acc-balance", "acc-balance2"].forEach(id => set(id, fmtUsd(balance)));
    ["acc-equity", "acc-equity2"].forEach(id => set(id, fmtUsd(equity)));

    ["acc-float", "acc-float2"].forEach(id => {
      const e = $(id);
      if (!e) return;
      e.textContent = `${sgn(fl)}${fmtUsd(fl)}`;
      e.className = `stat-tile-val ${cls(fl)}`;
    });

    set("acc-broker", acc.broker || "-");
    set("acc-leverage", `1:${acc.leverage || 100}`);
    set("acc-margin", fmtUsd(acc.margin || 0));
    set("acc-marginlevel", `${Number(acc.margin_level || 0).toFixed(1)}%`);
  }
}

async function loadSignal() {
  const d = await api(`/signal?symbol=${encodeURIComponent(currentSymbol)}`);
  if (!d) return;

  const sigText = parseSignalText(d);
  const score = Number(d.score || 0);
  const ict = d.ict || {};
  const refPrice = Number(d.price ?? d.last_price ?? d.ob50 ?? d.ob_50 ?? ict.ob50 ?? 0);
  if (Number.isFinite(refPrice) && refPrice > 0) {
    const hadPrice = Number.isFinite(lastPrice) && lastPrice > 0;
    lastPrice = refPrice;
    if ($("manual-entry")) $("manual-entry").value = formatPrice(lastPrice);
    if (!hadPrice) seedManualLevels(manualSide);
    else syncDragLinesFromInputs();
  }

  html("signal-badge", badge(sigText));
  set("signal-symbol", d.symbol || currentSymbol);
  set("signal-ob50", Number((d.ob50 ?? d.ob_50 ?? ict.ob50 ?? 0)).toFixed(5));
  set("signal-sl", Number((d.sl ?? ict.sl ?? 0)).toFixed(5));
  set("signal-tp", Number((d.tp ?? ict.tp ?? 0)).toFixed(5));

  set("hero-signal-text", sigText);
  set("hero-score-big", `score=${score.toFixed(3)}`);
  updateHeroGlow(sigText);

  set("ict-obtop", Number(ict.ob_top || d.ob_top || 0).toFixed(5));
  set("ict-ob50", Number((ict.ob50 ?? d.ob50 ?? d.ob_50 ?? 0)).toFixed(5));
  set("ict-obbot", Number(ict.ob_bottom || d.ob_bottom || 0).toFixed(5));
  set("ict-fvgtop", Number(ict.fvg_top || 0).toFixed(5));
  set("ict-fvgbot", Number(ict.fvg_bottom || 0).toFixed(5));
  set("ict-sl", Number(ict.sl || d.sl || 0).toFixed(5));
  set("ict-tp", Number(ict.tp || d.tp || 0).toFixed(5));
  set("ict-bos", ict.bos || "-");

  const pct = Math.max(0, Math.min(1, score));
  const ring = $("conf-ring-fill");
  if (ring) {
    ring.style.strokeDashoffset = String(380 - (380 * pct));
    ring.setAttribute("class", `conf-ring-fill ${pct > 0.55 ? "green" : pct < 0.45 ? "red" : "yellow"}`);
  }
  set("conf-ring-pct", `${Math.round(pct * 100)}%`);

  const mc = d.model_contributions || {};
  const mcEl = $("model-confidence");
  if (mcEl) {
    mcEl.innerHTML = Object.entries(mc)
      .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
      .map(([m, s]) => {
        const w = Math.round(Number(s || 0) * 100);
        return `<div class="weight-row"><div class="weight-name">${m}</div><div class="weight-bar"><div class="weight-fill" style="width:${w}%;background:var(--accent)"></div></div><div class="weight-pct">${w}%</div></div>`;
      }).join("");
  }
}

async function loadRisk() {
  const [r, h] = await Promise.all([api("/risk/summary"), api("/portfolio/health")]);
  if (!r) return;

  set("risk-pct", `${Number(r.risk_pct || 1).toFixed(1)}%`);
  set("risk-daily", `${Number(r.daily_limit_pct || 5).toFixed(1)}%`);
  set("risk-maxdd", `${Number(r.max_drawdown_pct || 10).toFixed(1)}%`);
  set("risk-openpos", r.open_positions || 0);
  set("risk-trades", r.total_trades || 0);
  set("risk-streak", r.loss_streak || 0);
  set("risk-winrate", fmtPct(r.win_rate || 0));

  const pnl = Number(r.daily_pnl || 0);
  const pnlEl = $("risk-dailypnl");
  if (pnlEl) {
    pnlEl.textContent = `${sgn(pnl)}${fmtUsd(pnl)}`;
    pnlEl.className = `kpi-val ${cls(pnl)}`;
  }

  if (h) {
    set("health-score", `${Math.round(Number(h.score || 0) * 100)}/100`);
    set("health-status", h.status || "-");
    const bar = $("health-bar");
    if (bar) bar.style.width = `${Math.round(Number(h.score || 0) * 100)}%`;
  }
}

async function loadPositions() {
  const data = await api("/positions");
  const tb = $("positions-tbody");
  if (!tb) return;

  if (!data || !Object.keys(data).length) {
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#888">No open positions</td></tr>';
    renderChartPositions({});
    return;
  }

  tb.innerHTML = Object.entries(data).map(([tid, t]) => {
    const pnl = Number(t.pnl || 0);
    const type = String(t.order_type || t.type || "BUY").toUpperCase();
    return `<tr><td>${tid}</td><td><b>${t.symbol || "?"}</b></td><td><span class="badge ${String(t.type || "BUY").toLowerCase()}">${type}</span></td><td>${t.lot || 0}</td><td>${Number(t.entry || 0).toFixed(5)}</td><td>${Number(t.sl || 0).toFixed(5)} / ${Number(t.tp || 0).toFixed(5)}</td><td class="${cls(pnl)}">${sgn(pnl)}${fmtUsd(pnl)}</td><td><button class="btn btn-danger btn-sm" data-close-ticket="${tid}">Close</button></td></tr>`;
  }).join("");
  renderChartPositions(data);
}

function renderChartPositions(data) {
  const tb = $("chart-positions-tbody");
  if (!tb) return;

  const entries = Object.entries(data || {}).filter(([, t]) =>
    String(t.symbol || "").toUpperCase() === currentSymbol
  );

  if (!entries.length) {
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:18px;color:#888">No open trades for this chart symbol</td></tr>';
    return;
  }

  tb.innerHTML = entries.map(([tid, t]) => {
    const pnl = Number(t.pnl || 0);
    const baseType = String(t.type || "BUY").toUpperCase();
    const type = String(t.order_type || baseType).toUpperCase();
    return `<tr><td>${tid}</td><td><span class="badge ${baseType.toLowerCase()}">${type}</span></td><td>${Number(t.entry || 0).toFixed(5)}</td><td>${Number(t.sl || 0).toFixed(5)}</td><td>${Number(t.tp || 0).toFixed(5)}</td><td class="${cls(pnl)}">${sgn(pnl)}${fmtUsd(pnl)}</td><td><button class="btn btn-danger btn-sm" data-close-ticket="${tid}">Close</button></td></tr>`;
  }).join("");
}

async function loadHistory() {
  const data = await api("/history?limit=20");
  const tb = $("history-tbody");
  if (!tb) return;

  if (!data || !data.length) {
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#888">No history</td></tr>';
    return;
  }

  tb.innerHTML = [...data].reverse().map(t => {
    const pnl = Number(t.pnl || 0);
    const type = String(t.type || "BUY").toUpperCase();
    const note = t.note || (String(t.source || "").toLowerCase() === "backtest" ? "Backtest" : "-");
    return `<tr><td>${t.date || "?"}</td><td><b>${t.symbol || "?"}</b></td><td><span class="badge ${type.toLowerCase()}">${type}</span></td><td>${t.lot || 0}</td><td class="${cls(pnl)}">${sgn(pnl)}${fmtUsd(pnl)}</td><td>${t.ticket || "?"}</td><td>${note}</td></tr>`;
  }).join("");
}

async function loadModels() {
  const data = await api("/models/status");
  const g = $("models-grid");
  if (!g || !data) return;

  const iconMap = {
    candle_patterns: "CP",
    correlation: "CO",
    divergence: "DV",
    elliott_wave: "EW",
    fibonacci: "FB",
    liquidity_sweep: "LS",
    mtf_confluence: "MC",
    news_volatility: "NV",
    regime: "RG",
    rsi_trend: "RS",
    sessions: "SS",
    smart_money: "SM",
    supply_demand: "SD",
    volume_orderflow: "VO",
    wyckoff: "WY",
    ensemble_head: "EH",
  };

  g.innerHTML = Object.entries(data).map(([name, d]) => {
    const sig = Number(d.signal || 0.5);
    const acc = Number(d.accuracy || 0.5);
    const w = Number(d.weight || 1);
    const action = sig > 0.55 ? "BUY" : sig < 0.45 ? "SELL" : "HOLD";
    const c = action === "BUY" ? "green" : action === "SELL" ? "red" : "yellow";
    const icon = iconMap[name] || "AI";

    return `<div class="model-card" data-model="${name}" title="Click for details"><div class="model-card-top"><div class="model-card-icon">${icon}</div><div><div class="model-card-name">${name}</div><div class="model-card-spec">v${d.version || 1}</div></div><div class="model-card-action ${action}">${action}</div></div><div class="model-bar-wrap"><div class="model-bar-label"><span>Signal</span><span>${Math.round(sig * 100)}%</span></div><div class="model-bar-track"><div class="model-bar-fill ${c}" style="width:${sig * 100}%"></div></div></div><div class="model-bar-wrap"><div class="model-bar-label"><span>Accuracy</span><span>${Math.round(acc * 100)}%</span></div><div class="model-bar-track"><div class="model-bar-fill accent" style="width:${acc * 100}%"></div></div></div><div class="model-card-footer"><span class="model-card-weight">w=${w.toFixed(2)}</span><span class="model-card-acc">${d.enabled !== false ? "ACTIVE" : "OFF"}</span></div></div>`;
  }).join("");
}

async function loadWeights() {
  const data = await api("/models/status");
  const c = $("weights-list");
  if (!c || !data) return;

  const total = Object.values(data).reduce((s, d) => s + Number(d.weight || 1), 0) || 1;
  c.innerHTML = Object.entries(data).map(([name, d]) => {
    const p = (Number(d.weight || 1) / total) * 100;
    return `<div class="weight-row"><div class="weight-name">${name}</div><div class="weight-bar"><div class="weight-fill" style="width:${p}%;background:var(--accent)"></div></div><div class="weight-pct">${p.toFixed(1)}%</div><div class="weight-trades">acc ${(Number(d.accuracy || 0) * 100).toFixed(0)}%</div></div>`;
  }).join("");
}

async function loadBacktest() {
  const d = await api("/backtest/status");
  if (!d) return;

  set("backtest-status", d.status || "idle");
  set("backtest-progress", `${Number(d.progress || 0).toFixed(0)}%`);

  const bar = $("backtest-bar");
  if (bar) bar.style.width = `${Number(d.progress || 0)}%`;

  const r = d.result || {};
  set("bt-symbol", r.symbol || "-");
  set("bt-days", r.days || "-");
  set("bt-trades", r.trades || "-");
  set("bt-winrate", r.win_rate != null ? fmtPct(r.win_rate) : "-");
  set("bt-roi", r.roi != null ? `${Number(r.roi).toFixed(2)}%` : "-");
  set("bt-maxdd", r.max_dd != null ? `${Number(r.max_dd).toFixed(2)}%` : "-");
  set("bt-sharpe", r.sharpe != null ? Number(r.sharpe).toFixed(2) : "-");
}

async function loadCSV() {
  try {
    const r = await fetch("./supervisor_results.csv", { cache: "no-store" });
    if (!r.ok) return;

    const text = await r.text();
    const lines = text.trim().split("\n");
    if (lines.length < 2) return;

    const headers = lines[0].split(",");
    const rows = lines.slice(1).map(l => {
      const cols = l.split(",");
      return Object.fromEntries(headers.map((h, i) => [h, cols[i]]));
    });

    const tb = $("results-tbody");
    if (!tb) return;

    tb.innerHTML = rows.slice(-60).reverse().map(rw =>
      `<tr><td>${rw.step}</td><td>${rw.date}</td><td>${Number(rw.close || 0).toFixed(5)}</td><td>${Number(rw.ensemble || 0).toFixed(3)}</td><td>${badge(rw.signal)}</td><td>${rw.actual_up === "1" ? "UP" : "DOWN"}</td></tr>`
    ).join("");
  } catch {
    // ignore CSV read errors
  }
}

async function loadServerLog() {
  const data = await api("/log?limit=40");
  if (!data || !Array.isArray(data)) return;

  data.forEach(e => {
    if (!logLines.some(l => l.now === e.time && l.text === e.msg)) {
      logLines.push({ now: e.time, text: e.msg, type: e.level || "info" });
    }
  });

  if (logLines.length > 250) logLines = logLines.slice(-250);

  const t = $("log-terminal");
  if (t) {
    t.innerHTML = logLines.slice(-90).map(l =>
      `<div class="log-entry"><span class="log-time">${l.now}</span><span class="log-text ${l.type}">${l.text}</span></div>`
    ).join("");
  }
}

async function loadIntegrationStatus() {
  const data = await api("/integrations/status");
  if (!data) return;
  set("int-telegram-status", data.telegram_configured ? "READY" : "SET TOKEN");
  set("int-voice-status", data.voice_available ? "READY" : "MISSING");
  set("int-vision-status", data.vision_available ? "READY" : "MISSING");
  set("int-synthetic-status", data.synthetic_ready ? "READY" : "OFF");
}

function renderSyntheticRows(rows) {
  const tb = $("synthetic-tbody");
  if (!tb) return;
  if (!rows || !rows.length) {
    tb.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:20px;color:#888">No synthetic runs yet.</td></tr>';
    return;
  }
  tb.innerHTML = rows.map(row =>
    `<tr><td>${row.run}</td><td>${row.trades}</td><td>${fmtPct(row.win_rate)}</td><td class="${cls(row.roi)}">${row.roi.toFixed(2)}%</td><td>${row.max_dd.toFixed(2)}%</td><td>${fmtUsd(row.ending_balance)}</td><td>${row.bias}</td></tr>`
  ).join("");
}

function initIntegrationsPanel() {
  $("voice-send-btn")?.addEventListener("click", async () => {
    const text = $("voice-text-input")?.value?.trim() || "";
    if (!text) return;
    set("voice-output", "Sending voice prompt...");
    const res = await post("/integrations/voice/chat", { text });
    set("voice-output", res?.reply || res?.error || "No reply");
  });

  $("vision-run-btn")?.addEventListener("click", async () => {
    const symbol = $("vision-symbol-input")?.value || currentSymbol;
    const timeframe = $("vision-timeframe-input")?.value || "M15";
    set("vision-output", "Analyzing structure...");
    const res = await post("/integrations/vision/structure", { symbol, timeframe, count: 120 });
    if (!res) {
      set("vision-output", "No response from vision integration.");
      return;
    }
    if (res.error) {
      set("vision-output", res.error);
      return;
    }
    const events = res.events || [];
    if (!events.length) {
      set("vision-output", `No structure events found for ${symbol} ${timeframe}.`);
      return;
    }
    set("vision-output", events.map(e => `${e.pattern} | ${e.direction} | ${(Number(e.confidence || 0) * 100).toFixed(1)}% | t=${e.time}`).join("\n"));
  });

  $("synthetic-run-btn")?.addEventListener("click", async () => {
    const symbol = $("synthetic-symbol-input")?.value || currentSymbol;
    const runs = Number($("synthetic-runs-input")?.value || 8);
    const days = Number($("synthetic-days-input")?.value || 30);
    const seed = Number($("synthetic-seed-input")?.value || 4242);
    renderSyntheticRows([]);
    const res = await post("/synthetic/run", { symbol, runs, days, seed });
    renderSyntheticRows(res?.scenarios || []);
  });

  const bindTicketCloser = containerId => {
    $(containerId)?.addEventListener("click", async event => {
      const btn = event.target.closest("[data-close-ticket]");
      if (!btn) return;
      const ticket = btn.getAttribute("data-close-ticket");
      const res = await post("/trades/close_ticket", { ticket });
      addLog(res?.queued_mt ? `Close queued for ticket ${ticket}` : `Close requested for ticket ${ticket}`, "info");
      setTimeout(() => refreshAll({ forceHeavy: true }), 600);
    });
  };

  bindTicketCloser("positions-tbody");
  bindTicketCloser("chart-positions-tbody");
}

function syncForexSmartBotSection() {
  const frame = $("forexsmartbot-frame");
  const link = $("forexsmartbot-open-link");
  const src = getForexSmartBotStandaloneUrl();
  if (frame && frame.dataset.src !== src) {
    frame.dataset.src = src;
    frame.src = src;
  }
  if (link) link.href = src;
}

async function refreshAll({ forceHeavy = false } = {}) {
  if (!isConnected) return;
  if (refreshInFlight) {
    refreshQueued = true;
    return;
  }

  refreshInFlight = true;

  try {
    await Promise.allSettled([
      loadStatus(),
      loadSignal(),
      loadRisk(),
      loadPositions(),
    ]);

    const now = Date.now();
    const shouldRunHeavy = forceHeavy || (now - lastHeavyRefreshAt >= HEAVY_REFRESH_MS);
    if (shouldRunHeavy) {
      await Promise.allSettled([
        loadHistory(),
        loadModels(),
        loadWeights(),
        loadBacktest(),
        loadServerLog(),
        loadIntegrationStatus(),
      ]);
      lastHeavyRefreshAt = now;
    }

    lastSyncTime = new Date();
    set("settings-last-sync", lastSyncTime.toLocaleTimeString());
    syncForexSmartBotSection();
  } finally {
    refreshInFlight = false;
    if (refreshQueued) {
      refreshQueued = false;
      setTimeout(() => refreshAll({ forceHeavy: false }), 0);
    }
  }
}

async function doAction(action) {
  const map = {
    "start-trading": () => post("/trading/enable", { enabled: true }),
    "stop-trading": () => post("/trading/enable", { enabled: false }),
    pause: () => post("/trading/pause"),
    resume: () => post("/trading/resume"),
    "close-all": () => post("/trades/close_all"),
    retrain: () => post("/retrain"),
    "reset-weights": () => post("/models/reset_weights"),
    "mode-auto": () => post("/trading/mode", { mode: "auto" }),
    "mode-semi": () => post("/trading/mode", { mode: "semi" }),
    "mode-off": () => post("/trading/mode", { mode: "off" }),
    "run-backtest": () => post("/backtest/run", {
      symbol: ($("bt-symbol-input")?.value || "EURUSD"),
      days: Number($("bt-days-input")?.value || 30),
    }),
  };

  if (map[action]) {
    const res = await map[action]();
    if (action === "close-all" && res) {
      addLog(res.queued_mt ? "Close-all queued to MT bridge" : `Closed ${res.closed || 0} trades`, "info");
    }
    setTimeout(refreshAll, 500);
  }
}

function initNav() {
  document.querySelectorAll(".sidebar-item[data-section]").forEach(item => {
    item.addEventListener("click", () => {
      openSection(item.dataset.section);
      if (item.dataset.section === "section-chart") {
        setTimeout(syncDragLinesFromInputs, 60);
      }
    });
  });
}

function initSymbolSelect() {
  const sel = $("nav-symbol-select");
  if (!sel) return;

  const hasCurrent = [...sel.options].some(o => o.value.toUpperCase() === currentSymbol);
  if (hasCurrent) sel.value = currentSymbol;

  sel.addEventListener("change", () => {
    applySymbol(sel.value, { fromBackend: false, persist: true });
    if (isConnected) loadSignal();
    if (isConnected) loadPositions();
  });
}

function bindBridgeDisplay() {
  const el = $("bridge-url");
  if (!el) return;

  el.title = "Open settings";
  el.style.cursor = "pointer";
  el.addEventListener("click", () => {
    openSection("section-settings");
    $("settings-bridge-url")?.focus();
  });
}

function startClock() {
  const e = $("nav-time");
  if (!e) return;

  const render = () => {
    e.textContent = new Date().toUTCString().slice(17, 25) + " UTC";
  };

  render();
  setInterval(render, 1000);
}

function initSettings() {
  setBridge(BRIDGE, { persist: true, syncInput: true });
  set("settings-poll-rate", `${POLL} ms`);

  const brokerEl = $("settings-broker-select");
  if (brokerEl) {
    brokerEl.value = brokerMode;
    brokerEl.addEventListener("change", async () => {
      brokerMode = String(brokerEl.value || "auto").toLowerCase();
      localStorage.setItem(STORAGE.brokerMode, brokerMode);
      saveChartTemplate();
      if (isConnected) {
        await post("/mt/connect", { enabled: true, broker_mode: brokerMode });
      }
      addLog(`Broker mode set to ${brokerMode.toUpperCase()}`, "info");
    });
  }

  const autoEl = $("settings-auto-symbol");
  if (autoEl) {
    autoEl.checked = autoSymbolSync;
    autoEl.addEventListener("change", () => {
      autoSymbolSync = !!autoEl.checked;
      localStorage.setItem(STORAGE.autoSymbol, autoSymbolSync ? "1" : "0");
      addLog(`Auto symbol sync ${autoSymbolSync ? "enabled" : "disabled"}`, "info");
      saveChartTemplate();
    });
  }

  const layoutInput = $("settings-deriv-layout-url");
  if (layoutInput) layoutInput.value = derivLayoutUrl;

  $("settings-connect-toggle")?.addEventListener("click", async () => {
    if (isConnected) {
      disconnectBridge();
      return;
    }
    await connectBridge({ silent: false });
  });

  $("settings-save-btn")?.addEventListener("click", () => {
    const raw = $("settings-bridge-url")?.value || BRIDGE;
    try {
      setBridge(normalizeBridgeURL(raw), { persist: true, syncInput: true });
      addLog(`Saved backend URL: ${BRIDGE}`, "success");
      saveChartTemplate();
    } catch {
      addLog("Invalid backend URL", "error");
    }
  });

  $("settings-apply-layout-btn")?.addEventListener("click", () => {
    derivLayoutUrl = String($("settings-deriv-layout-url")?.value || "").trim();
    localStorage.setItem(STORAGE.derivLayoutUrl, derivLayoutUrl);
    renderDerivChart(currentSymbol);
    saveChartTemplate();
    addLog("Applied Deriv layout URL", "success");
  });

  $("chart-open-new-tab-btn")?.addEventListener("click", () => {
    window.open(buildDerivChartUrl(currentSymbol), "_blank", "noopener");
  });

  $("chart-save-template-btn")?.addEventListener("click", () => {
    saveChartTemplate();
    addLog("Template saved locally", "success");
  });

  $("chart-download-template-btn")?.addEventListener("click", () => {
    downloadTemplateFile();
    addLog("Template downloaded", "success");
  });

  $("chart-upload-template-input")?.addEventListener("change", async (ev) => {
    const file = ev?.target?.files?.[0];
    if (!file) return;

    try {
      await uploadTemplateFile(file);
      const input = $("chart-upload-template-input");
      if (input) input.value = "";
      renderDerivChart(currentSymbol);
    } catch {
      addLog("Template upload failed", "error");
    }
  });
}

function loadSavedTemplateAtStartup() {
  const raw = localStorage.getItem(STORAGE.chartTemplate);
  if (!raw) return;

  try {
    const parsed = JSON.parse(raw);
    applyChartTemplate(parsed, { persist: false });
  } catch {
    // ignore bad template data
  }
}

function initModelModal() {
  const modal = $("model-info-modal");
  if (!modal) return;

  $("model-info-close-btn")?.addEventListener("click", () => modal.classList.remove("open"));
  modal.addEventListener("click", ev => {
    if (ev.target === modal) modal.classList.remove("open");
  });

  $("models-grid")?.addEventListener("click", ev => {
    const card = ev.target.closest(".model-card[data-model]");
    if (!card) return;
    showModelInfo(card.dataset.model || "model");
  });
}

function initManualTradingPanel() {
  ["drag-entry-line", "drag-sl-line", "drag-tp-line"].forEach(id => {
    const el = $(id);
    if (el) el.dataset.label = id.replace("drag-", "").replace("-line", "").toUpperCase();
  });
  setupDragLine("drag-entry-line");
  setupDragLine("drag-sl-line");
  setupDragLine("drag-tp-line");

  $("manual-order-type")?.addEventListener("change", ev => {
    manualOrderType = String(ev.target.value || "BUY_MARKET").toUpperCase();
    manualSide = currentManualSideFromType(manualOrderType);
    updateManualModeUI();
    seedManualLevels(manualSide);
  });

  $("manual-arm-entry-btn")?.addEventListener("click", () => {
    manualDragTarget = "entry";
    updateManualModeUI();
  });
  $("manual-arm-sl-btn")?.addEventListener("click", () => {
    manualDragTarget = "sl";
    updateManualModeUI();
  });
  $("manual-arm-tp-btn")?.addEventListener("click", () => {
    manualDragTarget = "tp";
    updateManualModeUI();
  });

  $("manual-reset-lines-btn")?.addEventListener("click", () => seedManualLevels(manualSide));
  $("manual-buy-btn")?.addEventListener("click", async () => {
    manualSide = "BUY";
    manualOrderType = String($("manual-order-type")?.value || "BUY_MARKET").replace(/^SELL/, "BUY");
    if ($("manual-order-type")) $("manual-order-type").value = manualOrderType;
    updateManualModeUI();
    await placeManualTrade("BUY");
  });
  $("manual-sell-btn")?.addEventListener("click", async () => {
    manualSide = "SELL";
    manualOrderType = String($("manual-order-type")?.value || "SELL_MARKET").replace(/^BUY/, "SELL");
    if ($("manual-order-type")) $("manual-order-type").value = manualOrderType;
    updateManualModeUI();
    await placeManualTrade("SELL");
  });

  $("manual-sl")?.addEventListener("change", syncDragLinesFromInputs);
  $("manual-tp")?.addEventListener("change", syncDragLinesFromInputs);
  $("manual-limit-price")?.addEventListener("change", syncDragLinesFromInputs);
  $("manual-entry")?.addEventListener("change", () => {
    const val = Number($("manual-entry")?.value || lastPrice || 0);
    if (Number.isFinite(val) && val > 0) {
      if (orderTypeNeedsPendingEntry(manualOrderType)) lastPrice = val;
      syncDragLinesFromInputs();
    }
  });

  $("market-watchlist")?.addEventListener("click", ev => {
    const btn = ev.target.closest("[data-watch-symbol]");
    if (!btn) return;
    applySymbol(btn.dataset.watchSymbol, { fromBackend: false, persist: true });
    addLog(`Pinned watchlist symbol ${btn.dataset.watchSymbol}`, "info");
    if (isConnected) {
      loadSignal();
      loadPositions();
    }
  });

  if ($("manual-side-label")) $("manual-side-label").value = manualSide;
  if ($("manual-order-type")) $("manual-order-type").value = manualOrderType;
  updateManualModeUI();
  setTimeout(() => seedManualLevels(manualSide), 120);
}

window.calcLot = function calcLot() {
  const bal = parseFloat($("calc-balance")?.value || 10000);
  const risk = parseFloat($("calc-risk")?.value || 1);
  const sl = parseFloat($("calc-sl")?.value || 20);
  const riskUsd = bal * risk / 100;
  const lot = Math.max(0.01, Math.round((riskUsd / (sl * 10)) / 0.01) * 0.01);
  set("calc-result", `Lot: ${lot.toFixed(2)}   ($${riskUsd.toFixed(2)} risk)`);
};

document.addEventListener("DOMContentLoaded", async () => {
  initNav();
  initSymbolSelect();
  startClock();
  initSettings();
  bindBridgeDisplay();
  initModelModal();
  initManualTradingPanel();
  initIntegrationsPanel();
  syncForexSmartBotSection();

  document.querySelectorAll("[data-action]").forEach(b => {
    b.addEventListener("click", () => doAction(b.dataset.action));
  });

  $("refresh-btn")?.addEventListener("click", async () => {
    if (!isConnected) {
      addLog("Not connected. Use Settings > Connect.", "warn");
      return;
    }
    await refreshAll({ forceHeavy: true });
  });

  $("nav-settings-btn")?.addEventListener("click", () => {
    openSection("section-settings");
  });

  document.querySelector(".nav-hamburger")?.addEventListener("click", () => {
    document.querySelector(".sidebar")?.classList.toggle("open");
  });

  loadSavedTemplateAtStartup();
  applySymbol(currentSymbol, { fromBackend: false, persist: true });
  renderDerivChart(currentSymbol);

  setConnectionState(false, "Offline");
  addLog(`Backend URL ready: ${BRIDGE}`, "info");

  const autoConnected = await connectBridge({ silent: true });
  if (autoConnected) addLog(`Auto-connected to ${BRIDGE}`, "success");
  else addLog("Auto-connect failed. Click Connect in Settings.", "warn");

  await loadCSV();
  setInterval(refreshAll, POLL);
  setInterval(loadCSV, 20000);
  setInterval(() => {
    if (!isConnected && !userDisconnected) {
      connectBridge({ silent: true });
    }
  }, AUTO_RECONNECT_MS);
});
