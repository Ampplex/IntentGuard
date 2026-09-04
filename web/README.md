# IntentGuard demo page

React and Vite. Every call it makes reaches the real backend: extraction runs on
Bedrock, negotiation runs the actual buyer and merchant agents, the decision is
the deterministic engine, and an order is created against Razorpay's test-mode
API. There is no fixture path and nothing is stubbed.

```
npm install
npm run build     # emits into ../src/intentguard/api/static/app
```

Then serve the whole thing from one process:

```
cd .. && PYTHONPATH=src .venv/bin/python -m uvicorn \
    intentguard.api.app:create_app --factory --port 8000
```

Open http://127.0.0.1:8000.

`npm run dev` also works and proxies `/api` to port 8000, which is quicker while
changing the page.

Test card 4100 2800 0000 1007, CVV 123, expiry 12/26. Test UPI test@razorpay.
