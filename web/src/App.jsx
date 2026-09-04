import { useEffect, useState } from "react";
import * as api from "./api";
import { rupees } from "./format";

const EXAMPLES = [
  {
    label: "Clean purchase",
    instruction: "Buy me a pair of new running shoes, budget 5000 rupees. No subscriptions.",
    hostility: "none",
  },
  {
    label: "Hidden subscription",
    instruction: "Buy me a pair of new running shoes, budget 5000 rupees. No subscriptions.",
    hostility: "trial_subscription",
  },
  {
    label: "Shipping after the quote",
    instruction: "Buy me a pair of new running shoes, budget 4300 rupees.",
    hostility: "hidden_shipping",
  },
  {
    label: "Product swapped",
    instruction: "Buy me a pair of new running shoes, budget 5000 rupees.",
    hostility: "substitution",
  },
  {
    label: "Injection in the description",
    instruction: "Buy me a pair of new running shoes, budget 5000 rupees.",
    hostility: "injection",
  },
  {
    label: "Nothing to go on",
    instruction: "Get me a decent laptop, nothing too pricey.",
    hostility: "none",
  },
];

const HOSTILITIES = [
  ["none", "honest"],
  ["hidden_shipping", "adds shipping after the quote"],
  ["trial_subscription", "free trial that converts"],
  ["paid_addon", "paid add-on"],
  ["currency_swap", "quotes in another currency"],
  ["substitution", "swaps the product"],
  ["quantity_inflation", "ships more than asked"],
  ["total_mismatch", "total disagrees with the items"],
  ["unmodelled_field", "term the schema has no slot for"],
  ["injection", "prompt injection in the description"],
  ["excluded_material", "uses an excluded material"],
];

function Step({ n, title, state, children }) {
  return (
    <div className={`step ${state === "pending" ? "pending" : ""}`}>
      <div className="step-head">
        <span className="step-n">{n}</span>
        <span className="step-title">{title}</span>
        {state === "running" && <span className="chip muted spin">running</span>}
        {state && !["pending", "running"].includes(state) && (
          <span className={`chip ${state}`}>{state}</span>
        )}
      </div>
      {children && <div className="step-body">{children}</div>}
    </div>
  );
}

export default function App() {
  const [instruction, setInstruction] = useState(EXAMPLES[1].instruction);
  const [hostility, setHostility] = useState(EXAMPLES[1].hostility);
  const [concession, setConcession] = useState("haggle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [config, setConfig] = useState(null);
  const [mandate, setMandate] = useState(null);
  const [deal, setDeal] = useState(null);
  const [verdict, setVerdict] = useState(null);
  const [payment, setPayment] = useState(null);

  useEffect(() => {
    api.getConfig().then(setConfig).catch(() => setConfig(null));
  }, []);

  function reset() {
    setError(null);
    setMandate(null);
    setDeal(null);
    setVerdict(null);
    setPayment(null);
  }

  async function run() {
    reset();
    setBusy(true);
    try {
      const extracted = await api.extract(instruction);
      setMandate(extracted);
      if (!extracted.ledger) return;

      const negotiated = await api.negotiate(extracted.ledger, hostility, concession);
      setDeal(negotiated);
      if (!negotiated.offer) return;

      const { status, payload } = await api.createOrder(
        extracted.ledger,
        negotiated.offer,
        negotiated.negotiated_product,
      );
      setVerdict({ status, ...payload });
      if (status === 200) openCheckout(payload);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function openCheckout(order) {
    if (!window.Razorpay || !config) {
      setError("Razorpay checkout did not load.");
      return;
    }
    const rzp = new window.Razorpay({
      key: config.key_id,
      order_id: order.order_id,
      amount: order.amount,
      currency: order.currency,
      name: "IntentGuard",
      description: "Authorised by the intent gate",
      theme: { color: "#0f5f6b" },
      handler: async (response) => {
        const { status, payload } = await api.verifyPayment(response);
        setPayment(
          status === 200 && payload.verified
            ? { ok: true, id: payload.payment_id }
            : { ok: false, detail: payload.detail || "The signature did not verify." },
        );
      },
      modal: {
        ondismiss: () =>
          setPayment({ ok: false, detail: "You closed checkout. Nothing was charged." }),
      },
    });
    rzp.on("payment.failed", (r) =>
      setPayment({ ok: false, detail: r.error?.description || "Razorpay reported a failure." }),
    );
    rzp.open();
  }

  const decision = verdict?.decision ?? (verdict?.order_id ? "ALLOW" : null);

  return (
    <div className="wrap">
      <header className="mast">
        <p className="eyebrow">Razorpay AI Buildathon · Track 01</p>
        <h1>IntentGuard</h1>
        <p className="standfirst">
          An AI buyer negotiates with a merchant, and a deterministic gate decides whether the
          final cart still matches what the user authorised — before Razorpay is called.
        </p>
        <div className="badges">
          <span className="chip on">Razorpay test mode</span>
          {mandate?.backend && <span className="chip muted">{mandate.backend}</span>}
          <span className="chip muted">no model in the decision path</span>
        </div>
      </header>

      <div className="grid">
        <div>
          <div className="card">
            <h2>What the user asked for</h2>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              spellCheck="false"
            />
            <div className="examples">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex.label}
                  type="button"
                  onClick={() => {
                    setInstruction(ex.instruction);
                    setHostility(ex.hostility);
                    reset();
                  }}
                >
                  {ex.label}
                </button>
              ))}
            </div>

            <label htmlFor="hostility">How the merchant behaves</label>
            <select
              id="hostility"
              value={hostility}
              onChange={(e) => setHostility(e.target.value)}
            >
              {HOSTILITIES.map(([value, text]) => (
                <option key={value} value={value}>
                  {text}
                </option>
              ))}
            </select>

            <label htmlFor="concession">How it negotiates</label>
            <select
              id="concession"
              value={concession}
              onChange={(e) => setConcession(e.target.value)}
            >
              <option value="haggle">haggles a little each round</option>
              <option value="meet">meets the target</option>
              <option value="stubborn">never moves</option>
              <option value="oscillating">moves without converging</option>
            </select>

            <button onClick={run} disabled={busy}>
              {busy ? "Running…" : "Run it"}
            </button>
            {error && <p className="err">{error}</p>}

            <div className="hint">
              Test card 4100 2800 0000 1007 · CVV 123 · expiry 12/26
              <br />
              Test UPI test@razorpay
            </div>
            <p className="note">
              The page never sends an amount. The server derives it from the decision.
            </p>
          </div>
        </div>

        <div className="card tight">
          <Step
            n="1"
            title="Read the instruction"
            state={!mandate ? "pending" : mandate.ledger ? "ALLOW" : "ESCALATE"}
          >
            {mandate ? (
              mandate.ledger ? (
                <dl className="kv">
                  <dt>ceiling</dt>
                  <dd>{rupees(mandate.ledger.hard.max_total_paise)}</dd>
                  <dt>category</dt>
                  <dd>{mandate.ledger.hard.category}</dd>
                  <dt>condition</dt>
                  <dd>{mandate.ledger.hard.condition ?? "any"}</dd>
                  <dt>recurring</dt>
                  <dd>{mandate.ledger.hard.recurring_allowed ? "allowed" : "not allowed"}</dd>
                  <dt>read by</dt>
                  <dd>{mandate.backend}</dd>
                </dl>
              ) : (
                <>
                  <p>No defensible mandate could be built, so nothing was spent.</p>
                  <div className="finding ESCALATE">
                    <div className="code">ASKING THE USER</div>
                    <p>{mandate.question}</p>
                  </div>
                </>
              )
            ) : (
              "waiting"
            )}
          </Step>

          <Step
            n="2"
            title="Negotiate, without showing the ceiling"
            state={!deal ? "pending" : "ALLOW"}
          >
            {deal ? (
              <>
                <dl className="kv">
                  <dt>merchant sees the ceiling</dt>
                  <dd>{deal.ceiling_visible_to_merchant ? "yes" : "no"}</dd>
                  <dt>buyer aims at</dt>
                  <dd>{rupees(deal.target_paise)}</dd>
                  <dt>ended</dt>
                  <dd>
                    {deal.ending} after {deal.exchanges} exchange
                    {deal.exchanges === 1 ? "" : "s"}
                  </dd>
                </dl>
                <div className="rounds">
                  {deal.rounds.map((r) => (
                    <div key={r.number} className={`round ${r.note === "final offer" ? "final" : ""}`}>
                      <span className="n">r{r.number}</span>
                      <span>{rupees(r.quoted_total_paise)}</span>
                      <span className="ask">
                        {r.asked_for_paise ? `asked ${rupees(r.asked_for_paise)}` : r.note}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              "waiting"
            )}
          </Step>

          <Step n="3" title="Decide" state={decision ?? "pending"}>
            {verdict ? (
              verdict.status === 409 ? (
                <>
                  {verdict.violations.map((v) => (
                    <div key={v.code} className="finding BLOCK">
                      <div className="code">{v.code}</div>
                      <p>{v.explanation}</p>
                    </div>
                  ))}
                  <p className="note">
                    Razorpay was not called. Not called and rolled back — not called.
                  </p>
                </>
              ) : (
                <dl className="kv">
                  <dt>order</dt>
                  <dd>{verdict.order_id}</dd>
                  <dt>amount</dt>
                  <dd>{rupees(verdict.amount)}</dd>
                  <dt>receipt</dt>
                  <dd>{verdict.receipt}</dd>
                  <dt>offer hash</dt>
                  <dd style={{ wordBreak: "break-all" }}>{verdict.offer_hash}</dd>
                </dl>
              )
            ) : (
              "waiting"
            )}
          </Step>

          <Step
            n="4"
            title="Pay and verify the signature"
            state={!payment ? "pending" : payment.ok ? "ALLOW" : "BLOCK"}
          >
            {payment ? (
              payment.ok ? (
                <>
                  <p>
                    Razorpay's signature checks out against the order, so this payment is
                    genuine rather than merely reported.
                  </p>
                  <dl className="kv">
                    <dt>payment</dt>
                    <dd>{payment.id}</dd>
                  </dl>
                </>
              ) : (
                <p>{payment.detail}</p>
              )
            ) : (
              "waiting"
            )}
          </Step>
        </div>
      </div>
    </div>
  );
}
