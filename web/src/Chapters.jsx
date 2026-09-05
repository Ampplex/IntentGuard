import { useRef } from "react";
import { motion, useScroll, useTransform } from "motion/react";

// One diagram per chapter, driven by where you are inside that chapter rather
// than by "has it entered the viewport". Scrubbing is the difference between a
// picture that fades in and one that explains: the reader controls the pace, so
// the field really does lift out of the sentence as they scroll past it.
//
// Every repeated element is its own component. Calling useTransform inside a
// .map() put a hook inside a loop, which is React error #310, and it took the
// whole page down to a white screen. Hooks belong at the top level of a
// component, so each row is one.

/** Progress through this section: 0 at its top edge, 1 near its bottom. */
function useSectionScroll(ref) {
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start 0.85", "end 0.35"],
  });
  return scrollYProgress;
}

/** One field arriving in the mandate card. */
function MandateRow({ progress, at, label, value }) {
  const opacity = useTransform(progress, [at, at + 0.2], [0, 1]);
  const x = useTransform(progress, [at, at + 0.2], [-10, 0]);
  return (
    <motion.div className="viz-row" style={{ opacity, x }}>
      <span>{label}</span>
      <code>{value}</code>
    </motion.div>
  );
}

/** One: the sentence you type, taken apart into the fields that bind. */
export function MandateVisual() {
  const ref = useRef(null);
  const p = useSectionScroll(ref);

  const words = [
    { text: "buy me", lit: false },
    { text: "running shoes", lit: true },
    { text: "budget 5000 rupees", lit: true },
    { text: "no subscriptions", lit: true },
  ];
  const rows = [
    { label: "category", value: "footwear" },
    { label: "max_total_paise", value: "500000" },
    { label: "recurring_allowed", value: "false" },
  ];

  const sentenceFade = useTransform(p, [0, 0.35], [1, 0.3]);
  const cardRise = useTransform(p, [0.2, 0.75], [26, 0]);
  const cardFade = useTransform(p, [0.2, 0.6], [0, 1]);

  return (
    <div className="viz" ref={ref}>
      <motion.div className="viz-sentence" style={{ opacity: sentenceFade }}>
        {words.map((w) => (
          <span key={w.text} className={w.lit ? "lit" : ""}>
            {w.text}
          </span>
        ))}
      </motion.div>
      <motion.div className="viz-card" style={{ y: cardRise, opacity: cardFade }}>
        <span className="viz-card-title">the mandate</span>
        {rows.map((r, i) => (
          <MandateRow
            key={r.label}
            progress={p}
            at={0.3 + i * 0.12}
            label={r.label}
            value={r.value}
          />
        ))}
      </motion.div>
    </div>
  );
}

/** The one field the seller never receives, being struck out. */
function StruckRow({ progress, name }) {
  const scaleX = useTransform(progress, [0.35, 0.7], [0, 1]);
  return (
    <div className="viz-row struck">
      <span>{name}</span>
      <motion.i style={{ scaleX }} />
    </div>
  );
}

/** Two: the same mandate, and the copy the seller is handed. */
export function BlindVisual() {
  const ref = useRef(null);
  const p = useSectionScroll(ref);

  const fields = [
    { name: "category", kept: true },
    { name: "quantity", kept: true },
    { name: "condition", kept: true },
    { name: "max_total_paise", kept: false },
    { name: "currency", kept: true },
  ];
  const shift = useTransform(p, [0.15, 0.6], [18, 0]);
  const fade = useTransform(p, [0.15, 0.5], [0, 1]);

  return (
    <div className="viz viz-two" ref={ref}>
      <div className="viz-card">
        <span className="viz-card-title">what you authorised</span>
        {fields.map((f) => (
          <div className="viz-row" key={f.name}>
            <span>{f.name}</span>
          </div>
        ))}
      </div>
      <motion.div className="viz-card" style={{ x: shift, opacity: fade }}>
        <span className="viz-card-title">what the seller receives</span>
        {fields.map((f) =>
          f.kept ? (
            <div className="viz-row" key={f.name}>
              <span>{f.name}</span>
            </div>
          ) : (
            <StruckRow key={f.name} progress={p} name={f.name} />
          ),
        )}
      </motion.div>
    </div>
  );
}

/** One check landing as the scan passes it. */
function CheckRow({ progress, at, code }) {
  const opacity = useTransform(progress, [at, at + 0.06], [0.22, 1]);
  const x = useTransform(progress, [at, at + 0.06], [-6, 0]);
  const scale = useTransform(progress, [at, at + 0.06], [0.4, 1]);
  return (
    <motion.div className="viz-check" style={{ opacity, x }}>
      <motion.span className="viz-tick" style={{ scale }}>
        <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path
            d="M2.5 6.2 5 8.6l4.5-5"
            stroke="currentColor"
            strokeWidth="1.9"
            strokeLinecap="round"
          />
        </svg>
      </motion.span>
      <code>{code}</code>
    </motion.div>
  );
}

/** Three: the checks running, one after another, as you scroll through them. */
export function GateVisual({ codes }) {
  const ref = useRef(null);
  const p = useSectionScroll(ref);
  // The engine's own vocabulary, not a list written for this page.
  const shown = codes.slice(0, 10);
  const sweep = useTransform(p, [0.05, 0.9], ["0%", "100%"]);

  return (
    <div className="viz" ref={ref}>
      <div className="viz-scan">
        <motion.span style={{ height: sweep }} />
      </div>
      <div className="viz-checks">
        {shown.map((code, i) => (
          <CheckRow
            key={code}
            progress={p}
            at={0.06 + (i / Math.max(shown.length, 1)) * 0.8}
            code={code}
          />
        ))}
      </div>
    </div>
  );
}

/** One of the three ways a decision can come out. */
function Lane({ progress, at, name, note, tone }) {
  const opacity = useTransform(progress, [at, at + 0.12], [0.25, 1]);
  const x = useTransform(progress, [at, at + 0.12], [-12, 0]);
  const scaleX = useTransform(progress, [at, at + 0.2], [0, 1]);
  return (
    <motion.div className={`viz-lane ${tone}`} style={{ opacity, x }}>
      <motion.span className="viz-lane-fill" style={{ scaleX }} />
      <b>{name}</b>
      <span>{note}</span>
    </motion.div>
  );
}

/** Four: three ways out, and only one of them reaches the payment rail. */
export function OutcomeVisual() {
  const ref = useRef(null);
  const p = useSectionScroll(ref);
  const lanes = [
    { name: "ALLOW", note: "reaches Razorpay", tone: "allow" },
    { name: "BLOCK", note: "409, no call made", tone: "block" },
    { name: "ESCALATE", note: "a person is asked", tone: "ask" },
  ];
  return (
    <div className="viz" ref={ref}>
      <div className="viz-lanes">
        {lanes.map((lane, i) => (
          <Lane key={lane.name} progress={p} at={0.15 + i * 0.22} {...lane} />
        ))}
      </div>
    </div>
  );
}
