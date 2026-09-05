import { useEffect, useRef, useState } from "react";
import * as api from "./api";
import { rupees } from "./format";

// The buyer's agent, as a conversation.
//
// The setup questions come first and are asked, not configured: which seller
// you are dealing with decides what the gate will have to catch, and burying
// that in a dropdown made the demo look like a form with a chat bolted on.
// Every answer here drives the same endpoints the console used -- extraction on
// Bedrock, a real negotiation, a real decision, a real Razorpay order.

const BEHAVIOURS = [
  ["none", "An honest seller", "Offers the matched product with normal terms."],
  ["hidden_shipping", "Adds shipping after quoting", "Adds a ₹499 delivery charge after showing the product price."],
  ["trial_subscription", "Slips in a free trial that renews", "Adds a free first month that becomes a ₹299 monthly subscription."],
  ["paid_addon", "Adds a paid extra", "Adds a ₹799 extended warranty to the cart."],
  ["substitution", "Sends a different product", "Offers another product instead of the one the buyer requested."],
  ["quantity_inflation", "Ships more than asked", "Sends one extra unit beyond the requested quantity."],
  ["currency_swap", "Quotes another currency", "Quotes in USD even though the authorization is in INR."],
  ["total_mismatch", "Total disagrees with the items", "Declares a total different from all item prices and charges added together."],
  ["injection", "Writes instructions to the AI in the listing", "Adds text that tries to make the AI ignore the buyer's rules."],
  ["excluded_material", "Uses a material you ruled out", "Offers a product containing a material the buyer explicitly rejected."],
  ["unmodelled_field", "Adds a term nothing models", "Adds a contract term IntentGuard does not know how to evaluate."],
];

const BEHAVIOUR_DESCRIPTIONS = Object.fromEntries([
  ["none", "Normal merchant offer"],
  ["hidden_shipping", "Merchant adds shipping after quoting"],
  ["trial_subscription", "Merchant adds a renewing trial"],
  ["paid_addon", "Merchant adds a paid extra"],
  ["substitution", "Merchant changes the product"],
  ["quantity_inflation", "Merchant sends extra quantity"],
  ["currency_swap", "Merchant quotes another currency"],
  ["total_mismatch", "Merchant total disagrees with its line items"],
  ["injection", "Merchant listing contains instructions to the AI"],
  ["excluded_material", "Merchant uses an excluded material"],
  ["unmodelled_field", "Merchant adds an unsupported term"],
]);

const STYLES = [
  ["haggle", "Haggles a little", "Makes a few reasonable counteroffers, then decides."],
  ["meet", "Meets your price", "Keeps negotiating toward the price you requested."],
  ["stubborn", "Will not move", "Accepts the seller's first offer without negotiating."],
  ["oscillating", "Never settles", "Keeps trying different counteroffers until the limit is reached."],
];

const Tick = () => (
  <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path
      d="M2.5 6.2 5 8.6l4.5-5"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    />
  </svg>
);
const Cross = () => (
  <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path
      d="M3 3l6 6M9 3l-6 6"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    />
  </svg>
);
const Bang = () => (
  <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path
      d="M6 3v3.4M6 8.8v.2"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    />
  </svg>
);

function Mark({ state }) {
  const icon =
    state === "ok" ? (
      <Tick />
    ) : state === "no" ? (
      <Cross />
    ) : state === "ask" ? (
      <Bang />
    ) : null;
  return <span className={`mark ${state}`}>{icon}</span>;
}

function Raw({ label, value }) {
  if (value === undefined || value === null) return null;
  return (
    <details className="raw">
      <summary>{label}</summary>
      <pre className="raw">{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

function NegotiationTranscript({ rounds }) {
  if (!rounds?.length) return null;
  return (
    <details className="transcript">
      <summary>Agent-to-agent negotiation ({rounds.length} quotes)</summary>
      <div className="transcript-list">
        {rounds.map((round) => (
          <div className="transcript-round" key={round.number}>
            <span className="transcript-round-number">Round {round.number}</span>
            <div className="transcript-message merchant-message">
              <b>Merchant agent</b>
              <span>Offers {rupees(round.quoted_total_paise)}</span>
            </div>
            {round.asked_for_paise !== null && (
              <div className="transcript-message buyer-message">
                <b>Buyer agent</b>
                <span>Asks for {rupees(round.asked_for_paise)}</span>
              </div>
            )}
            {round.asked_for_paise === null && (
              <span className="transcript-note">Final offer</span>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}

/** What the gate did, in the order it did it. */
function Trace({ run }) {
  const { mandate, deal, verdict, timing } = run;
  const ms = (k) =>
    timing[k] === undefined ? null : `${(timing[k] / 1000).toFixed(2)}s`;
  const decision = verdict?.decision ?? (verdict?.order_id ? "ALLOW" : null);
  const noOffer = deal && !deal.offer;

  return (
    <div className="trace">
      <div className="trace-row">
        <Mark state={!mandate ? "idle" : mandate.ledger ? "ok" : "ask"} />
        <div className="what">
          <b>Read what you asked for</b>
          <span>
            {!mandate
              ? "waiting"
              : mandate.ledger
                ? `ceiling ${rupees(mandate.ledger.hard.max_total_paise)} · ${mandate.ledger.hard.category}`
                : "could not be read confidently"}
          </span>
        </div>
        <span className="ms">{ms("read")}</span>
      </div>

      <div className="trace-row">
        <Mark state={!deal ? "idle" : noOffer ? "ask" : "ok"} />
        <div className="what">
          <b>Negotiated without showing your ceiling</b>
          <span>
            {!deal
              ? "waiting"
              : noOffer
                ? "the seller had nothing matching"
                : `${deal.exchanges} exchange${deal.exchanges === 1 ? "" : "s"} · ${
                    deal.ceiling_visible_to_merchant
                      ? "ceiling leaked"
                      : "ceiling never sent"
                  }`}
          </span>
        </div>
        <span className="ms">{ms("negotiate")}</span>
      </div>

      <div className="trace-row">
        <Mark
          state={
            !verdict
              ? "idle"
              : decision === "ALLOW"
                ? "ok"
                : decision === "BLOCK"
                  ? "no"
                  : "ask"
          }
        />
        <div className="what">
          <b>Checked the final cart</b>
          <span>
            {!verdict
              ? noOffer
                ? "nothing to check"
                : "waiting"
              : decision === "ALLOW"
                ? `${rupees(verdict.amount)} authorised`
                : `${verdict.violations?.length ?? 0} problem${
                    verdict.violations?.length === 1 ? "" : "s"
                  } found`}
          </span>
        </div>
        <span className="ms">{ms("decide")}</span>
      </div>
    </div>
  );
}

function FinalOffer({ deal, verdict }) {
  const product = deal?.offer?.product?.title || deal?.negotiated_product;
  const amount = verdict?.status === 200 ? verdict.amount : deal?.offer?.total_paise;
  if (!product || amount === undefined || amount === null) return null;
  return (
    <div className="final-offer">
      <div>
        <span className="final-offer-label">Final merchant offer</span>
        <strong>{product}</strong>
      </div>
      <span className="final-offer-price">{rupees(amount)}</span>
    </div>
  );
}

function DecisionReason({ run }) {
  const violations = run.verdict?.violations ?? [];
  if (!violations.length) return null;
  return (
    <div className="decision-reason">
      <b>Why it stopped</b>
      {run.behaviour && (
        <span className="decision-source">
          Test merchant: {BEHAVIOUR_DESCRIPTIONS[run.behaviour] ?? run.behaviour}
        </span>
      )}
      {violations.map((violation) => (
        <span key={violation.code}>
          <strong>{violation.code}</strong> {violation.explanation}
        </span>
      ))}
    </div>
  );
}

function RunCard({ run, onConfirm }) {
  const { mandate, deal, verdict } = run;
  const decision = verdict?.decision ?? (verdict?.order_id ? "ALLOW" : null);
  return (
    <>
      <Trace run={run} />
      <FinalOffer deal={deal} verdict={verdict} />
      <DecisionReason run={run} />
      {deal && !deal.offer && (
        <div className="verdict ESCALATE">
          <div className="verdict-name">Nothing on offer</div>
          <p>
            This seller does not stock{" "}
            {mandate?.ledger?.hard?.product_ref
              ? `"${mandate.ledger.hard.product_ref}"`
              : "anything matching that"}
            , so it returned no quote rather than sending the nearest thing.
            Nothing was charged.
          </p>
        </div>
      )}
      {verdict?.status === 409 && (
        <div className={`verdict ${decision}`}>
          <div className="verdict-name">
            {decision} · Razorpay was never called
          </div>
          {verdict.violations?.map((v) => (
            <div key={v.code}>
              <code>{v.code}</code>
              <p>{v.explanation}</p>
            </div>
          ))}
          {verdict.escalation_question && <p>{verdict.escalation_question}</p>}
          {decision === "ESCALATE" && onConfirm && (
            <button
              className="btn btn-dark btn-sm confirm-btn"
              onClick={() => onConfirm(run)}
            >
              Confirm authorization and continue
            </button>
          )}
        </div>
      )}
      {verdict?.status === 200 && (
        <div className="verdict ALLOW">
          <div className="verdict-name">Allowed</div>
          <dl className="kv">
            <dt>Amount</dt>
            <dd>{rupees(verdict.amount)}</dd>
            <dt>Order</dt>
            <dd>{verdict.order_id}</dd>
          </dl>
        </div>
      )}
      <NegotiationTranscript rounds={deal?.rounds} />
      {deal?.offer?.raw_description && (
        <p className="fineprint" style={{ marginTop: 8 }}>
          Listing text (untrusted): {deal.offer.raw_description}
        </p>
      )}
      <Raw label="what the seller was sent" value={deal?.merchant_view} />
      <Raw label="the offer that came back" value={deal?.offer} />
      <Raw label="the full decision" value={verdict} />
    </>
  );
}

export default function Chat({ open, onClose, seed, onOrder }) {
  const [step, setStep] = useState("behaviour");
  const [behaviour, setBehaviour] = useState(null);
  const [style, setStyle] = useState(null);
  const [msgs, setMsgs] = useState([
    {
      from: "bot",
      text: "I am your buying agent. First, choose the merchant behavior you want to test me against.",
    },
  ]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const bottom = useRef(null);

  const say = (m) => setMsgs((prev) => [...prev, m]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, busy]);

  // Arriving from a product card: the instruction is written for you.
  useEffect(() => {
    if (!seed || !open) return;
    setDraft(seed);
  }, [seed, open]);

  function pickBehaviour(value, label) {
    setBehaviour(value);
    say({ from: "user", text: label });
    say({ from: "bot", text: "Now choose how aggressively your buyer agent should bargain." });
    setStep("style");
  }

  function pickStyle(value, label) {
    setStyle(value);
    say({ from: "user", text: label });
    say({
      from: "bot",
      text: "Ready. Tell me what to buy and what you are willing to spend. For example, “buy me a pair of running shoes, budget 5000 rupees, no subscriptions”.",
    });
    setStep("shopping");
  }

  async function send(instruction) {
    const text = instruction.trim();
    if (!text || busy) return;
    setDraft("");
    setError(null);
    say({ from: "user", text });
    setBusy(true);

    const run = { mandate: null, deal: null, verdict: null, timing: {}, behaviour };
    const timed = async (key, work) => {
      const t0 = performance.now();
      try {
        return await work();
      } finally {
        run.timing[key] = performance.now() - t0;
      }
    };

    try {
      const mandate = await timed("read", () => api.extract(text));
      run.mandate = mandate;
      if (!mandate.ledger) {
        say({ from: "bot", text: mandate.question, run: { ...run } });
        return;
      }

      const deal = await timed("negotiate", () =>
        api.negotiate(mandate.ledger, behaviour, style),
      );
      run.deal = deal;
      if (!deal.offer) {
        say({
          from: "bot",
          text: "I could not find that with this seller, so I stopped rather than buying something else.",
          run: { ...run },
        });
        return;
      }

      const { status, payload } = await timed("decide", () =>
        api.createOrder(mandate.ledger, deal.offer, deal.negotiated_product),
      );
      run.verdict = { status, ...payload };

      if (status === 200) {
        say({
          from: "bot",
          text: `Cleared. ${rupees(payload.amount)} for ${deal.negotiated_product}. Opening checkout.`,
          run: { ...run },
        });
        onOrder(payload);
      } else {
        say({
          from: "bot",
          text: "I stopped this one. Here is exactly what was wrong with it.",
          run: { ...run },
        });
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmRun(run) {
    if (busy || !run.mandate?.ledger || !run.deal?.offer) return;
    setBusy(true);
    setError(null);
    try {
      const confirmedLedger = {
        ...run.mandate.ledger,
        status: "ACTIVE",
        human_confirmed: true,
      };
      const { status, payload } = await api.createOrder(
        confirmedLedger,
        run.deal.offer,
        run.deal.negotiated_product,
      );
      const nextRun = {
        ...run,
        mandate: { ...run.mandate, ledger: confirmedLedger },
        verdict: { status, ...payload },
      };
      setMsgs((previous) =>
        previous.map((message) =>
          message.run === run
            ? {
                ...message,
                text:
                  status === 200
                    ? `Cleared. ${rupees(payload.amount)} for ${run.deal.negotiated_product}. Opening checkout.`
                    : "I stopped this one. The final cart still did not pass the authorization checks.",
                run: nextRun,
              }
            : message,
        ),
      );
      if (status === 200) onOrder(payload);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // Hidden rather than unmounted. Returning null here threw away the whole
  // conversation every time the panel was closed -- including the seller you
  // had chosen and every decision you had just watched happen.
  return (
    <aside
      className="panel"
      role="dialog"
      aria-label="Buying agent"
      hidden={!open}
    >
      <div className="panel-head">
        <div>
          <h2>Your buying agent</h2>
          <p>every call is real</p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none">
            <path
              d="M4 4l8 8M12 4l-8 8"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>

      <div className="thread">
        {msgs.map((m, i) => (
          <div className={`msg ${m.from}`} key={i}>
            <span className="who">{m.from === "user" ? "You" : "AI"}</span>
            <div className="bubble">
              <p>{m.text}</p>
              {m.run && <RunCard run={m.run} onConfirm={confirmRun} />}
            </div>
          </div>
        ))}

        {step === "behaviour" && (
          <div className="choice-group">
            <p className="choice-label">Merchant behavior</p>
            <div className="choices">
            {BEHAVIOURS.map(([value, label, description]) => (
              <button
                key={value}
                className="choice"
                onClick={() => pickBehaviour(value, label)}
                aria-label={`Merchant behavior: ${label}`}
              >
                <span className="choice-title">{label}</span>
                <span className="choice-description">{description}</span>
              </button>
            ))}
            </div>
          </div>
        )}
        {step === "style" && (
          <div className="choice-group">
            <p className="choice-label">Buyer agent bargaining style</p>
            <div className="choices">
            {STYLES.map(([value, label, description]) => (
              <button
                key={value}
                className="choice"
                onClick={() => pickStyle(value, label)}
                aria-label={`Buyer agent bargaining style: ${label}`}
              >
                <span className="choice-title">{label}</span>
                <span className="choice-description">{description}</span>
              </button>
            ))}
            </div>
          </div>
        )}
        {busy && (
          <div className="msg bot">
            <span className="who">AI</span>
            <div className="bubble">
              <p>Negotiating…</p>
            </div>
          </div>
        )}
        {error && <p className="err">{error}</p>}
        <div ref={bottom} />
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={
            step === "shopping"
              ? "What should I buy?"
              : "Pick an option above first"
          }
          disabled={step !== "shopping" || busy}
          aria-label="Message your buying agent"
        />
        <button
          className="btn btn-dark btn-sm"
          type="submit"
          disabled={step !== "shopping" || busy}
        >
          Send
        </button>
      </form>
    </aside>
  );
}
