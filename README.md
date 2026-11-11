# दुकान AI · Dukaan AI

**Run your shop by talking to your phone.** Snap a product, speak an invoice, hear today's sales.
An AI agent does the work through **PayPal's Agent Toolkit** — catalog, invoices, reminders, reporting and disputes.

> Built for the **PayPal AI Hackathon 2026** · runs on PayPal **sandbox** · no GPU needed

- 🎥 **Demo video:** _add your YouTube link here_
- 🌐 **Live demo:** _add your Render link here_ (or run locally in 2 minutes, below)

---

## The problem
Millions of small shopkeepers run their business from a notebook. They're great at business, but payment
tools are built for people who are comfortable with forms, dashboards and English.

## What Dukaan AI does

| Say / do this | The agent does this (PayPal Agent Toolkit tool) |
|---|---|
| 🗣️ *"Sharma ji ko teen bag ka pandrah sau ka bill bhejo"* | Reads it back, waits for **"haan"**, then `create_invoice` → `send_invoice` → `get_invoice`, and shows a **scan-to-pay QR** |
| 📸 Hold a product up to the camera | Gemini Vision names it, **Channel3** finds market prices, then `create_product` adds it to the PayPal catalog |
| 🔔 *"Aaj ka hisaab batao"* / tap the bell | `list_invoices` + `list_disputes` → spoken briefing: money in, unpaid, disputes |
| 🗣️ *"Kaun kaun baaki hai?"* | `list_invoices` → who still owes money |
| 🗣️ *"Sharma ji ko yaad dilao"* | finds their open invoice → confirm → `send_invoice_reminder` |
| 🗣️ *"Koi shikayat hai?"* | `list_disputes` + `get_dispute` → AI drafts a factual reply from PayPal's data; *"accept kar do"* → confirm → `accept_dispute_claim` |
| 📒 Ledger tab | **AG Grid** view of PayPal invoices, catalog, and a full agent log |

Works in **Hindi, English and Hinglish**, by voice (Chrome/Edge Web Speech) or by typing.

## Trust rules (an agent that touches money must be boring and predictable)
1. **Nothing that writes to PayPal runs without a spoken or tapped "yes".** The agent reads back exactly what it will do.
2. **The AI extracts, code calculates.** The model only pulls out customer / item / quantity / price. Totals, briefings and
   unpaid lists are computed in Python from PayPal's own data.
3. **Every action is logged**: what was heard, which toolkit tool ran, and the result (Ledger → Agent log).
4. **Modes are always visible**: header chips show `PayPal SANDBOX/DEMO`, `AI LIVE/DEMO`, `Channel3 LIVE/DEMO`.

## How AI is used
| AI | Used for |
|---|---|
| **Google Gemini** (`gemini-2.5-flash`, configurable) | Understanding Hinglish voice commands into a structured intent (JSON) |
| **Gemini Vision** | Recognising a product from a camera photo (name, category, search query, price estimate) |
| **Gemini** | Drafting a short, factual dispute reply using only facts returned by PayPal |
| Browser Web Speech API | Speech-to-text and text-to-speech (`hi-IN`, `en-IN`) — not a model we host |

## Architecture
```
 Phone / laptop browser  ── voice (Web Speech) ── camera ── AG Grid ledger
            │  /api/command  /api/vision  /api/confirm  /api/briefing
            ▼
 FastAPI ── brain.py ──────► Gemini (intent · vision · dispute draft)
    │        agent.py  ──── plan → read-back → wait for "haan" → execute
    │        channel3.py ──► Channel3 product search (price grounding)
    ▼
 paypal_tools.py ── paypal_agent_toolkit.PayPalAPI.run(tool, params) ──► PayPal SANDBOX
 store.py (SQLite: catalog prices, customers, agent log)
```
**Demo mode** runs the *same* PayPal Agent Toolkit code (parameter validation + payload builders) but swaps its HTTP
client for an in-memory fake PayPal, so judges can try every flow with zero keys.

## Run it (Windows, ~2 minutes)
Needs **Python 3.11+** and Chrome or Edge.
```bat
git clone https://github.com/0xr4j/dukaan-ai.git
cd dukaan-ai
setup.bat
run.bat
```
Open **http://localhost:8000**. With no keys it runs in **DEMO** mode.

macOS / Linux: `./setup.sh` then `source .venv/bin/activate && uvicorn app.main:app --port 8000`

### Go live on the PayPal sandbox
Edit `.env` (created by setup):
```
PAYPAL_CLIENT_ID=...        # developer.paypal.com → Apps & Credentials → Sandbox → Create App
PAYPAL_CLIENT_SECRET=...
GEMINI_API_KEY=...          # https://aistudio.google.com/apikey (free)
CHANNEL3_API_KEY=...        # optional, hackathon promo PAYPAL-HACKATHON-2026
CURRENCY=USD
```
Restart `run.bat`. The header chips switch to **PayPal SANDBOX** / **AI LIVE**.
Invoices you send appear in your sandbox business account at https://www.sandbox.paypal.com.

### Try these
- `Sharma ji ko teen bag ka pandrah sau ka bill bhejo` → say **haan**
- `Invoice Priya for 2 rice bags at 120 each`
- `Aaj ka hisaab batao` · `Who hasn't paid?` · `Remind Sharma ji` · `Any disputes?`
- 📷 → photograph any product

### Tests
```bash
python -m pytest -q
```
The tests run every flow in demo mode through the real toolkit code path.

### Deploy (Render, free)
`render.yaml` is included: New → Blueprint → pick this repo → add the env vars.

## Honest limits
- PayPal sandbox only; no real money moves.
- Voice input uses the browser's speech recognition (best in Chrome/Edge).
- The demo-mode camera returns a sample item; real recognition needs a Gemini key.
- Dispute replies are drafted for the shopkeeper. The only dispute *action* the agent takes is `accept_dispute_claim`, after confirmation.
- PayPal's QR endpoint returns an image payload; the app also renders its own QR from the invoice's PayPal pay link.
- Domestic INR payments depend on PayPal account region; USD works on any sandbox business account.

## Built with
Python · FastAPI · **PayPal Agent Toolkit** (`paypal-agent-toolkit`) · PayPal Invoicing, Catalog, Disputes APIs ·
Google Gemini · Channel3 · AG Grid Community · Web Speech API · SQLite · segno (QR)

## License
MIT. See [LICENSE](LICENSE). AG Grid Community (MIT) is loaded from the jsDelivr CDN, or from `static/vendor/` if you place a local copy there.
