// Dukaan AI front end: voice in, voice out, camera, confirm cards, AG Grid ledger.
const $ = (s) => document.querySelector(s);
const feed = $("#feed");
let lang = "en";
let status = { symbol: "₹" };
let pendingId = null;
let gridApi = null;
let gridKind = "invoices";

const SUGGEST = {
  hi: ["Sharma ji ko teen bag ka pandrah sau ka bill bhejo", "Aaj ka hisaab batao", "Kaun kaun baaki hai?",
       "Sharma ji ko yaad dilao", "Koi shikayat hai?", "Parle G biscuit 10 rupaye mein jodo"],
  en: ["Invoice Priya for 2 rice bags at 120 each", "How did business go today?", "Who hasn't paid?",
       "Remind Sharma ji", "Any disputes?", "Add Parle G biscuit at 10 to catalog"],
};

const money = (v) => `${status.symbol}${Number(v || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return r.json();
}

// ---------- language ----------
function setLang(l) {
  lang = l;
  $("#langHi").classList.toggle("on", l === "hi");
  $("#langEn").classList.toggle("on", l === "en");
  document.querySelectorAll("[data-hi]").forEach((el) => (el.textContent = el.dataset[l]));
  $("#suggest").innerHTML = SUGGEST[l].map((s) => `<button>${esc(s)}</button>`).join("");
  $("#suggest").querySelectorAll("button").forEach((b) => (b.onclick = () => send(b.textContent)));
  try { localStorage.setItem("dukaan-lang", l); } catch (e) {}
}
$("#langHi").onclick = () => setLang("hi");
$("#langEn").onclick = () => setLang("en");

// ---------- speech out ----------
function speak(text) {
  if (!("speechSynthesis" in window) || !text) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/[₹$]/g, lang === "hi" ? "" : "$&"));
  u.lang = lang === "hi" ? "hi-IN" : "en-IN";
  const v = speechSynthesis.getVoices().find((v) => v.lang === u.lang);
  if (v) u.voice = v;
  u.rate = 1.02;
  speechSynthesis.speak(u);
}

// ---------- speech in ----------
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;
function listen(onText) {
  if (!SR) { $("#hint").textContent = "Voice needs Chrome/Edge. You can type below."; return; }
  if (rec) { rec.stop(); return; }
  rec = new SR();
  rec.lang = lang === "hi" ? "hi-IN" : "en-IN";
  rec.interimResults = true;
  $("#mic").classList.add("listening");
  $("#hint").textContent = lang === "hi" ? "Sun raha hoon…" : "Listening…";
  let finalText = "";
  rec.onresult = (e) => {
    const t = Array.from(e.results).map((r) => r[0].transcript).join(" ");
    $("#hint").textContent = "“" + t + "”";
    if (e.results[e.results.length - 1].isFinal) finalText = t;
  };
  rec.onerror = (e) => ($("#hint").textContent = "Mic error: " + e.error);
  rec.onend = () => {
    $("#mic").classList.remove("listening");
    rec = null;
    if (finalText) onText(finalText.trim());
    else $("#hint").textContent = $("#hint").dataset[lang];
  };
  rec.start();
}

const YES = /\b(haan|ha|haa|ji haan|yes|yeah|ok|okay|theek|bhej do|kar do|confirm|sure)\b|हाँ|हां/i;
const NO = /\b(nahi|nahin|na|no|cancel|mat|ruko|stop)\b|नहीं/i;

$("#mic").onclick = () =>
  listen((text) => {
    if (pendingId && YES.test(text)) return decide(true, text);
    if (pendingId && NO.test(text)) return decide(false, text);
    send(text);
  });

// ---------- chat rendering ----------
function bubble(who, html, meta) {
  const d = document.createElement("div");
  d.className = `msg ${who}`;
  d.innerHTML = html + (meta ? `<div class="meta">${meta}</div>` : "");
  feed.appendChild(d);
  feed.scrollTop = feed.scrollHeight;
  return d;
}

function itemsTable(items, total) {
  const rows = items.map((i) => `<tr><td>${esc(i.quantity)} × ${esc(i.name)}</td><td class="r">${money(i.quantity * i.unit_price)}</td></tr>`).join("");
  return `<table>${rows}<tr class="total"><td>Total</td><td class="r">${money(total)}</td></tr></table>`;
}

function renderCard(c) {
  if (!c || !c.kind) return c && c.error ? `<div class="card"><h4>Error</h4>${esc(c.error)}</div>` : "";
  switch (c.kind) {
    case "invoice_preview":
      return `<div class="card"><h4>Invoice to ${esc(c.customer)}</h4>${itemsTable(c.items, c.total)}<div class="meta">${esc(c.email)}</div></div>`;
    case "invoice_sent":
      return `<div class="card"><h4>✅ PayPal invoice sent · ${esc(c.status)}</h4>
        <div class="qr"><img alt="QR to pay" src="/api/qr.svg?url=${encodeURIComponent(c.pay_url)}">
        <div><b>${money(c.total)}</b><br>${esc(c.customer)}<br><a href="${esc(c.pay_url)}" target="_blank" rel="noopener">${esc(c.invoice_id)}</a></div></div></div>`;
    case "product_preview": {
      const comps = (c.market?.comparables || []).map((m) => `<div class="comp">${m.image ? `<img src="${esc(m.image)}" alt="">` : ""}<div>${esc((m.title || "").slice(0, 40))}</div><b>${esc(m.currency)} ${esc(m.price)}</b><div>${esc(m.store || "")}</div></div>`).join("");
      return `<div class="card"><h4>New catalog item</h4>
        ${c.photo ? `<img class="thumb" src="${c.photo}" alt="">` : ""}
        <table><tr><td>${esc(c.name)}</td><td class="r"><b>${money(c.price)}</b></td></tr></table>
        <div class="meta">Price from: ${esc(c.price_source)} · Channel3: ${esc(c.market?.mode)}${c.vision ? ` · Vision: ${esc(c.vision._engine)}` : ""}</div>
        ${comps ? `<div class="comps">${comps}</div>` : ""}</div>`;
    }
    case "product_added":
      return `<div class="card"><h4>✅ Added to PayPal catalog</h4>${esc(c.name)} · ${money(c.price)}<div class="meta">${esc(c.paypal_product_id)}</div></div>`;
    case "briefing":
      return `<div class="card"><h4>Last 24 hours</h4><div class="stat-row">
        <div class="stat"><b>${money(c.paid_total)}</b><span>${c.paid_count} paid</span></div>
        <div class="stat"><b>${money(c.unpaid_total)}</b><span>${c.unpaid_count} unpaid</span></div>
        <div class="stat"><b>${c.disputes}</b><span>disputes</span></div></div></div>`;
    case "unpaid":
      return `<div class="card"><h4>Unpaid invoices</h4><table>${c.rows.map((r) => `<tr><td>${esc(r.customer)}</td><td class="r">${money(r.amount)}</td></tr>`).join("")}
        <tr class="total"><td>Total</td><td class="r">${money(c.total)}</td></tr></table></div>`;
    case "reminder_preview":
    case "reminder_sent":
      return `<div class="card"><h4>${c.kind === "reminder_sent" ? "✅ Reminder sent" : "Payment reminder"}</h4>${esc(c.customer || c.who)} · ${money(c.amount)}</div>`;
    case "dispute":
      return `<div class="card"><h4>⚠️ Dispute ${esc(c.dispute_id)}</h4>
        <div><b>${esc(c.facts.buyer)}</b>: “${esc(c.facts.buyer_message || c.facts.reason)}”</div>
        ${c.facts.tracking ? `<div class="meta">Tracking ${esc(c.facts.tracking.carrier)} ${esc(c.facts.tracking.tracking_number)}: ${esc(c.facts.tracking.status)} ${esc(c.facts.tracking.delivered_on || "")}</div>` : ""}
        <h4 style="margin-top:10px">Drafted reply</h4><div>${esc(c.draft.reply)}</div>
        <div class="meta">💡 ${esc(c.draft.advice)}</div></div>`;
    case "dispute_closed":
      return `<div class="card"><h4>✅ Claim accepted</h4>${esc(c.dispute_id)}</div>`;
    default:
      return "";
  }
}

function showReply(res, extra = {}) {
  const card = { ...(res.card || {}), ...extra };
  let html = esc(res.say) + renderCard(card);
  if (res.paypal_tool) html += `<div class="tool">PayPal Agent Toolkit → ${esc(res.paypal_tool)}</div>`;
  if (res.type === "confirm") {
    pendingId = res.pending_id;
    html += `<div class="confirm"><button class="yes">${lang === "hi" ? "Haan, karo ✓" : "Yes, do it ✓"}</button><button class="no">${lang === "hi" ? "Nahi ✕" : "No ✕"}</button></div>`;
  }
  const b = bubble("bot", html, res.engine ? `understood by ${esc(res.engine)}` : "");
  const yes = b.querySelector(".yes"), no = b.querySelector(".no");
  if (yes) { yes.onclick = () => decide(true); no.onclick = () => decide(false); }
  speak(res.say);
  $("#hint").textContent = $("#hint").dataset[lang];
  if (res.type === "confirm") $("#hint").textContent = lang === "hi" ? "“Haan” ya “Nahi” boliye" : "Say “yes” or “no”";
}

async function send(text) {
  if (!text) return;
  bubble("me", esc(text));
  const wait = bubble("bot", "…");
  try {
    const res = await api("/api/command", { text });
    wait.remove();
    showReply(res);
  } catch (e) {
    wait.innerHTML = "⚠️ " + esc(e.message);
  }
}

async function decide(approve, heard) {
  if (!pendingId) return;
  const id = pendingId;
  pendingId = null;
  document.querySelectorAll(".confirm").forEach((c) => c.remove());
  bubble("me", esc(heard || (approve ? (lang === "hi" ? "Haan" : "Yes") : (lang === "hi" ? "Nahi" : "No"))));
  const wait = bubble("bot", "…");
  try {
    const res = await api("/api/confirm", { pending_id: id, approve });
    wait.remove();
    showReply(res);
    loadGrid();
  } catch (e) {
    wait.innerHTML = "⚠️ " + esc(e.message);
  }
}

$("#typeForm").onsubmit = (e) => {
  e.preventDefault();
  const v = $("#typeInput").value.trim();
  $("#typeInput").value = "";
  if (pendingId && (YES.test(v) || NO.test(v)) && v.split(" ").length <= 3) return decide(YES.test(v), v);
  send(v);
};

$("#brief").onclick = async () => {
  bubble("me", lang === "hi" ? "Aaj ka hisaab?" : "Today's briefing?");
  const res = await api(`/api/briefing?lang=${lang}`);
  showReply(res);
};

// ---------- camera ----------
let stream = null;
$("#cam").onclick = async () => {
  $("#camDialog").showModal();
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    $("#video").srcObject = stream;
  } catch (e) {
    $("#video").poster = "";
  }
};
function closeCam() {
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = null;
  $("#camDialog").close();
}
$("#camClose").onclick = closeCam;

async function sendPhoto(dataUrl) {
  closeCam();
  bubble("me", `<img class="thumb" src="${dataUrl}" alt="photo">`);
  const wait = bubble("bot", lang === "hi" ? "Dekh raha hoon…" : "Looking…");
  try {
    const res = await api("/api/vision", { image: dataUrl, lang });
    wait.remove();
    showReply(res, { photo: dataUrl });
  } catch (e) {
    wait.innerHTML = "⚠️ " + esc(e.message);
  }
}
$("#snap").onclick = () => {
  const v = $("#video"), c = $("#canvas");
  if (!v.videoWidth) return;
  const scale = Math.min(1, 900 / v.videoWidth);
  c.width = v.videoWidth * scale; c.height = v.videoHeight * scale;
  c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
  sendPhoto(c.toDataURL("image/jpeg", 0.85));
};
$("#fileIn").onchange = (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const img = new Image();
  img.onload = () => {
    const c = $("#canvas"), scale = Math.min(1, 900 / img.width);
    c.width = img.width * scale; c.height = img.height * scale;
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    sendPhoto(c.toDataURL("image/jpeg", 0.85));
  };
  img.src = URL.createObjectURL(f);
};

// ---------- views & ledger (AG Grid) ----------
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== "view-" + t.dataset.view));
  if (t.dataset.view === "ledger") loadGrid();
}));
document.querySelectorAll("[data-grid]").forEach((b) => (b.onclick = () => {
  document.querySelectorAll("[data-grid]").forEach((x) => x.classList.toggle("on", x === b));
  gridKind = b.dataset.grid;
  loadGrid();
}));
$("#refresh").onclick = () => loadGrid();

const fmtTime = (v) => { const d = new Date(v); return isNaN(d) ? (v || "") : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); };
const COLS = {
  invoices: [
    { field: "created_at", headerName: "When", width: 150, sort: "desc", valueFormatter: (p) => fmtTime(p.value) },
    { field: "customer", filter: true },
    { field: "items", flex: 1, minWidth: 160 },
    { field: "total", type: "numericColumn", valueFormatter: (p) => money(p.value) },
    { field: "status", cellStyle: (p) => ({ color: /PAID/.test(p.value) ? "#2b8a3e" : "#e8590c", fontWeight: 600 }) },
    { field: "paypal_invoice_id", headerName: "PayPal ID" },
  ],
  products: [
    { field: "name", flex: 1, editable: true },
    { field: "category" },
    { field: "price", type: "numericColumn", valueFormatter: (p) => money(p.value) },
    { field: "price_source", headerName: "Price from" },
    { field: "paypal_product_id", headerName: "PayPal ID" },
  ],
  activity: [
    { field: "ts", headerName: "When", width: 150, sort: "desc", valueFormatter: (p) => fmtTime(p.value) },
    { field: "heard", headerName: "Heard", flex: 1, minWidth: 160 },
    { field: "action" },
    { field: "paypal_tool", headerName: "Toolkit call", minWidth: 180 },
    { field: "mode", width: 100 },
  ],
};

async function loadGrid() {
  if (!window.agGrid) { $("#grid").textContent = "AG Grid failed to load (offline?)."; return; }
  const data = await api("/api/ledger");
  const opts = { columnDefs: COLS[gridKind], rowData: data[gridKind], defaultColDef: { sortable: true, resizable: true, minWidth: 100 },
                 pagination: true, paginationPageSize: 20 };
  if (gridApi) gridApi.destroy();
  gridApi = agGrid.createGrid($("#grid"), opts);
}

// ---------- boot ----------
(async function boot() {
  try { setLang(localStorage.getItem("dukaan-lang") || "en"); } catch (e) { setLang("en"); }
  status = await api("/api/status");
  $("#shopName").textContent = status.shop;
  const chip = (label, mode) => `<span class="chip ${mode === "DEMO" ? "demo" : "live"}">${label}: ${mode}</span>`;
  $("#modes").innerHTML = `<span class="chip pp">PayPal ${status.paypal}</span>` + chip("AI", status.ai) + chip("Channel3", status.channel3);
  bubble("bot", lang === "hi"
    ? "Namaste! 🙏 Main aapka dukaan sahayak hoon. Bill bhejna, saaman jodna, ya hisaab poochna ho, bas boliye."
    : "Namaste! 🙏 I'm your shop assistant. Ask me to send a bill, add a product with the camera, or tell you today's sales.");
})();
