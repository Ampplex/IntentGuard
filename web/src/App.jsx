import { useCallback, useEffect, useState } from "react";
import * as api from "./api";
import Chat from "./Chat.jsx";
import Landing from "./Landing.jsx";
import Shop from "./Shop.jsx";
import Stress from "./Stress.jsx";
import { rupees } from "./format";

const TEST_CARD = [
  ["Card", "4100 2800 0000 1007"],
  ["CVV", "123"],
  ["Expiry", "12/26"],
  ["Name", "any name"],
  ["UPI", "test@razorpay"],
];

function Shield() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2.5 4.5 5.6v6.1c0 4.6 3.2 8.4 7.5 9.8 4.3-1.4 7.5-5.2 7.5-9.8V5.6L12 2.5Z"
        stroke="#fff"
        strokeWidth="1.9"
        strokeLinejoin="round"
      />
      <path
        d="m8.8 12 2.3 2.3 4.1-4.5"
        stroke="#fff"
        strokeWidth="1.9"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Offered before Razorpay opens, because its window covers the page. */
function CardDialog({ order, copied, onCopy, onContinue, onCancel }) {
  if (!order) return null;
  return (
    <div
      className="scrim"
      role="dialog"
      aria-modal="true"
      aria-labelledby="card-title"
    >
      <div className="dialog">
        <div className="dialog-head">
          <h2 id="card-title">Authorised. Take the test card first.</h2>
          <p>
            Razorpay&rsquo;s window will cover this page, so copy what you need
            now. {rupees(order.amount)} on order{" "}
            <strong>{order.order_id}</strong>.
          </p>
        </div>
        <div className="dialog-body">
          {TEST_CARD.map(([label, value]) => (
            <div className="cardrow" key={label}>
              <span className="cardlabel">{label}</span>
              <span className="cardvalue">{value}</span>
              <button
                className="copy"
                onClick={() => onCopy(label, value)}
                aria-label={`Copy ${label}`}
              >
                {copied === label ? "copied" : "copy"}
              </button>
            </div>
          ))}
          <p className="fineprint" style={{ marginTop: 10 }}>
            Test mode. Any future expiry and any CVV are accepted, and no real
            money moves.
          </p>
        </div>
        <div className="dialog-foot">
          <button className="btn btn-quiet btn-sm" onClick={onCancel}>
            Not now
          </button>
          <button className="btn btn-primary btn-sm" onClick={onContinue}>
            Continue to Razorpay
          </button>
        </div>
      </div>
    </div>
  );
}

/** Which view a hash names. One definition, used by the initial state and
    the hashchange handler -- they disagreed, and #stress reached neither. */
function readView() {
  const hash = window.location.hash;
  if (hash === "#shop") return "shop";
  if (hash === "#stress") return "stress";
  return "landing";
}

export default function App() {
  const [view, setView] = useState(readView);
  const [catalog, setCatalog] = useState([]);
  const [config, setConfig] = useState(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [seed, setSeed] = useState(null);
  const [order, setOrder] = useState(null);
  const [copied, setCopied] = useState(null);
  const [note, setNote] = useState(null);

  useEffect(() => {
    api
      .getConfig()
      .then(setConfig)
      .catch(() => setConfig(null));
    api
      .getCatalog()
      .then(setCatalog)
      .catch(() => setCatalog([]));
    const onHash = () => setView(readView());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const start = useCallback(() => {
    window.location.hash = "#shop";
    setView("shop");
    window.scrollTo(0, 0);
  }, []);

  const openCheckout = useCallback(
    (o) => {
      if (!window.Razorpay || !config) {
        setNote("Razorpay checkout did not load.");
        return;
      }
      const rzp = new window.Razorpay({
        key: config.key_id,
        order_id: o.order_id,
        amount: o.amount,
        currency: o.currency,
        name: "IntentGuard",
        description: "Authorised by the intent gate",
        theme: { color: "#305eff" },
        handler: async (response) => {
          const { status, payload } = await api.verifyPayment(response);
          setNote(
            status === 200 && payload.verified
              ? `Paid and verified. Payment ${payload.payment_id}.`
              : payload.detail || "The signature did not verify.",
          );
        },
        modal: {
          ondismiss: () => setNote("You closed checkout. Nothing was charged."),
        },
      });
      rzp.on("payment.failed", (r) =>
        setNote(r.error?.description || "Razorpay reported a failure."),
      );
      rzp.open();
    },
    [config],
  );

  return (
    <>
      <header className="nav">
        <div className="wrap nav-in">
          <a
            className="logo"
            href="#"
            onClick={(e) => {
              e.preventDefault();
              window.location.hash = "";
              setView("landing");
            }}
          >
            <span className="logo-mark">
              <Shield />
            </span>
            <b>IntentGuard</b>
          </a>
          <div className="nav-right">
            <span className="tag">
              <span className="dot" />
              Razorpay test mode
            </span>
            {view === "landing" ? (
              <button className="btn btn-dark btn-sm" onClick={start}>
                Start shopping
              </button>
            ) : (
              <button
                className="btn btn-quiet btn-sm"
                onClick={() => setChatOpen(true)}
              >
                Open agent
              </button>
            )}
          </div>
        </div>
      </header>

      {view === "stress" ? (
        <Stress />
      ) : view === "landing" ? (
        <Landing onStart={start} />
      ) : (
        <Shop
          catalog={catalog}
          onAsk={(instruction) => {
            setSeed(instruction);
            setChatOpen(true);
          }}
        />
      )}

      {view === "shop" && !chatOpen && (
        <button className="chat-fab" onClick={() => setChatOpen(true)}>
          <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path
              d="M3 5.5A2.5 2.5 0 0 1 5.5 3h9A2.5 2.5 0 0 1 17 5.5v5A2.5 2.5 0 0 1 14.5 13H8l-4 3.5V13H5.5A2.5 2.5 0 0 1 3 10.5Z"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
          </svg>
          Ask the agent
        </button>
      )}

      <Chat
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        seed={seed}
        onOrder={(payload) => setOrder(payload)}
      />

      <CardDialog
        order={order}
        copied={copied}
        onCopy={async (label, value) => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(label);
          } catch {
            setCopied(null);
          }
        }}
        onContinue={() => {
          const o = order;
          setOrder(null);
          openCheckout(o);
        }}
        onCancel={() => {
          setOrder(null);
          setNote("You stopped before checkout. Nothing was charged.");
        }}
      />

      {note && (
        <div
          className="scrim"
          role="dialog"
          aria-modal="true"
          onClick={() => setNote(null)}
        >
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <div className="dialog-head">
              <h2 style={{ color: "var(--navy)" }}>Payment</h2>
              <p>{note}</p>
            </div>
            <div className="dialog-foot">
              <button
                className="btn btn-dark btn-sm"
                onClick={() => setNote(null)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
