const params = new URLSearchParams(window.location.search);
const BRIDGE = String(params.get("bridge") || "http://127.0.0.1:5050").replace(/\/+$/, "");

const $ = id => document.getElementById(id);
const set = (id, value) => {
  const el = $(id);
  if (el) el.textContent = value;
};

function usd(v) {
  return `$${Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function setHealth(ok, text) {
  const dot = $("fsb-status-dot");
  const badge = $("fsb-health-badge");
  if (dot) {
    dot.style.background = ok ? "var(--accent-2)" : "var(--danger)";
    dot.style.boxShadow = ok
      ? "0 0 0 6px rgba(124,255,200,0.18)"
      : "0 0 0 6px rgba(255,107,129,0.18)";
  }
  set("fsb-status-text", text);
  set("fsb-bridge-health", ok ? "Online" : "Offline");
  if (badge) {
    badge.textContent = ok ? "Bridge Online" : "Bridge Offline";
    badge.style.color = ok ? "var(--accent-2)" : "var(--danger)";
  }
}

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function refresh() {
  set("fsb-bridge-url", BRIDGE);
  const supervisorLink = `../command_center.html?bridge=${encodeURIComponent(BRIDGE)}`;
  const link = $("fsb-open-supervisor");
  if (link) link.href = supervisorLink;

  try {
    const snapshot = await fetchJson(`${BRIDGE}/ui/snapshot`);
    const status = snapshot.bridge || {};
    const account = snapshot.account || {};
    const mt = snapshot.mt || {};
    const portfolio = snapshot.portfolio || {};

    setHealth(true, "Bridge connected and ready");
    set("fsb-bridge-symbol", status.symbol || "-");
    set("fsb-mt-link", mt.connected ? "Attached" : "Waiting");
    set("fsb-mode", String(status.mode || "-").toUpperCase());
    set("fsb-broker", account.broker || "-");
    set("fsb-balance", usd(account.balance));
    set("fsb-equity", usd(account.equity));
    set("fsb-float", usd(Number(account.equity || 0) - Number(account.balance || 0)));
    set("fsb-open", String(portfolio.open_trades ?? 0));
  } catch (err) {
    setHealth(false, `Bridge unreachable: ${err.message || "network"}`);
    set("fsb-bridge-symbol", "-");
    set("fsb-mt-link", "-");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  $("fsb-refresh-btn")?.addEventListener("click", refresh);
  await refresh();
  setInterval(refresh, 5000);
});
