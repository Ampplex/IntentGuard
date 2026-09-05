import { useEffect, useRef, useState } from "react";
import Lenis from "lenis";
import {
  motion,
  useInView,
  useScroll,
  useSpring,
  useTransform,
} from "motion/react";
import * as api from "./api";
import GateScene from "./GateScene.jsx";
import { BlindVisual, GateVisual, MandateVisual, OutcomeVisual } from "./Chapters.jsx";
import { rupees } from "./format";

// The landing page as an explanation, not a brochure.
//
// Each scroll answers one question, in the order someone new actually asks it:
// what breaks, what you authorise, why the seller is kept in the dark, what
// checks the cart, what can come out, and what it is worth. The WebGL scene
// behind the first screens is the gate itself, and the figures are read from
// the runs the benchmark wrote -- nothing on this page is a number I typed in.

/** A section that arrives as it enters view. One movement, not a firework. */
function Reveal({ children, delay = 0, as = "div", className = "" }) {
  const ref = useRef(null);
  const seen = useInView(ref, { once: true, margin: "-12% 0px -12% 0px" });
  const Tag = motion[as];
  return (
    <Tag
      ref={ref}
      className={className}
      initial={{ opacity: 0, y: 22 }}
      animate={seen ? { opacity: 1, y: 0 } : undefined}
      transition={{ duration: 0.62, delay, ease: [0.22, 0.7, 0.3, 1] }}
    >
      {children}
    </Tag>
  );
}

/** A figure that counts up once, so a number is read rather than skimmed past. */
function Counter({ to, format, duration = 1100 }) {
  const ref = useRef(null);
  const seen = useInView(ref, { once: true, margin: "-20% 0px" });
  const [shown, setShown] = useState(0);

  useEffect(() => {
    if (!seen || !Number.isFinite(to)) return;
    let raf = 0;
    const started = performance.now();
    const step = (now) => {
      const t = Math.min((now - started) / duration, 1);
      // Ease out, so it settles rather than stopping dead.
      setShown(to * (1 - Math.pow(1 - t, 3)));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [seen, to, duration]);

  return <span ref={ref}>{format(shown)}</span>;
}

const CHAPTERS = [
  {
    id: "mandate",
    kicker: "One",
    title: "You say what you will accept",
    body: "A budget, a product, the things you rule out. That becomes a mandate: a ceiling in whole paise, a category, a condition, and whether a subscription is allowed at all. It is signed before the agent goes anywhere.",
    aside: "buy me running shoes, budget 5000 rupees, no subscriptions",
    asideLabel: "what you type",
  },
  {
    id: "blind",
    kicker: "Two",
    title: "The seller is never told your ceiling",
    body: "The agent negotiates on your behalf, and the seller receives a projection of your mandate with the budget removed. It cannot quote just under a number it has never seen. This is not a detail. It is most of the money.",
    aside: "max_total_paise",
    asideLabel: "absent from everything the seller receives",
  },
  {
    id: "gate",
    kicker: "Three",
    title: "Thirteen checks, on integers, before any payment",
    body: "The final cart is taken apart: total against ceiling, currency, quantity, condition, add-ons, recurrence, the arithmetic of the line items. Every check runs, so a cart that breaks the budget and hides a subscription is told both.",
    aside: "no model runs here",
    asideLabel: "a test walks the import graph to prove it",
  },
  {
    id: "outcome",
    kicker: "Four",
    title: "Allow, block, or ask a person",
    body: "Allow reaches Razorpay with the figure the engine checked, never one the page supplied. Block returns 409 and the payment rail is never touched. Ask is a real answer, not an error. When it cannot decide, it stops and asks you.",
    aside: "409",
    asideLabel: "what a refusal returns, before any call",
  },
];

export default function Landing({ onStart }) {
  const [m, setMetrics] = useState(null);
  const track = useRef(null);

  useEffect(() => {
    api
      .getMetrics()
      .then(setMetrics)
      .catch(() => setMetrics(null));
  }, []);

  // Smooth scrolling, because the page is a sequence and a jumpy scroll reads
  // as a list. Disabled for anyone who has asked for less movement.
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const lenis = new Lenis({ duration: 1.05, smoothWheel: true });
    let raf = 0;
    const loop = (time) => {
      lenis.raf(time);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      lenis.destroy();
    };
  }, []);

  const { scrollYProgress } = useScroll();
  const bar = useSpring(scrollYProgress, {
    stiffness: 120,
    damping: 28,
    mass: 0.4,
  });
  const heroFade = useTransform(scrollYProgress, [0, 0.16], [1, 0]);
  const heroLift = useTransform(scrollYProgress, [0, 0.16], [0, -60]);

  const rev = m?.revenue;
  const bench = m?.dashboard?.benchmark;
  const lat = m?.dashboard?.latency;
  const codes = m?.violation_codes ?? [];
  // The scene shows the proportion the benchmark produced, not a flattering one.
  const allowedShare = bench
    ? bench.confusion.ALLOW.ALLOW / Math.max(bench.cases, 1)
    : 0.5;

  return (
    <div ref={track}>
      <motion.div className="progress" style={{ scaleX: bar }} />

      <section className="stage">
        <GateScene allowedShare={allowedShare} />
        <motion.div
          className="stage-copy wrap"
          style={{ opacity: heroFade, y: heroLift }}
        >
          <p className="eyebrow">AI buying agent · payment guard</p>
          <h1>
            One guard for both sides.
            <br />
            Your agent can buy <em>safely</em>.
          </h1>
          <p className="lede">
            The buyer agent searches and negotiates without revealing your
            spending ceiling. IntentGuard guards both sides: it protects the
            buyer from unauthorized charges and the merchant from unclear,
            inconsistent, or manipulated orders. It checks the final cart and
            allows, blocks, or asks before Razorpay is called.
          </p>
          <div className="hero-actions">
            <button className="btn btn-primary" onClick={onStart}>
              Try the buying agent
            </button>
            <a className="btn btn-quiet" href="#mandate">
              Show me how
            </a>
          </div>
          <p className="scroll-hint">Scroll. Every screen explains one part</p>
        </motion.div>
      </section>

      {CHAPTERS.map((c, i) => (
        <section className="chapter" id={c.id} key={c.id}>
          <div className="wrap chapter-in">
            <Reveal>
              <p className="kicker">{c.kicker}</p>
              <h2>{c.title}</h2>
              <p className="chapter-body">{c.body}</p>
            </Reveal>
            <Reveal delay={0.12}>
              <div className="chapter-viz">
                {c.id === "mandate" && <MandateVisual />}
                {c.id === "blind" && <BlindVisual />}
                {c.id === "gate" && <GateVisual codes={codes} />}
                {c.id === "outcome" && <OutcomeVisual />}
                <div className="aside">
                  <code>{c.aside}</code>
                  <span>{c.asideLabel}</span>
                </div>
              </div>
            </Reveal>
          </div>
          {i === CHAPTERS.length - 1 && codes.length > 0 && (
            <Reveal delay={0.1}>
              <div className="wrap">
                <div className="codes">
                  {codes.map((code) => (
                    <code key={code}>{code}</code>
                  ))}
                </div>
                <p className="fineprint" style={{ marginTop: 12 }}>
                  The {codes.length} reasons a cart can be refused or
                  questioned, read from the engine&rsquo;s own enum. Each
                  carries an explanation written for a person about to lose
                  money.
                </p>
              </div>
            </Reveal>
          )}
        </section>
      ))}

      {rev && (
        <section className="chapter proof">
          <div className="wrap">
            <Reveal>
              <p className="kicker">What it is worth</p>
              <h2>The same {rev.mandates} mandates, run twice.</h2>
              <p className="chapter-body">
                Identical catalogue, identical negotiation. The only difference
                is whether the seller was told the ceiling.
              </p>
            </Reveal>

            <Reveal delay={0.1}>
              <div className="arms">
                <div className="arm">
                  <span className="arm-name">Ceiling hidden</span>
                  <div className="arm-track">
                    <motion.span
                      className="under"
                      initial={{ width: 0 }}
                      whileInView={{
                        width: `${rev.share_of_ceiling_hidden * 100}%`,
                      }}
                      viewport={{ once: true, margin: "-15%" }}
                      transition={{ duration: 1.1, ease: [0.22, 0.7, 0.3, 1] }}
                    />
                  </div>
                  <span className="arm-fig">
                    <Counter
                      to={rev.hidden.average_paid_paise}
                      format={(v) => rupees(Math.round(v))}
                    />
                  </span>
                </div>
                <div className="arm">
                  <span className="arm-name">Ceiling exposed</span>
                  <div className="arm-track">
                    <motion.span
                      className="over"
                      initial={{ width: 0 }}
                      whileInView={{
                        width: `${rev.share_of_ceiling_exposed * 100}%`,
                      }}
                      viewport={{ once: true, margin: "-15%" }}
                      transition={{
                        duration: 1.1,
                        delay: 0.15,
                        ease: [0.22, 0.7, 0.3, 1],
                      }}
                    />
                  </div>
                  <span className="arm-fig over">
                    <Counter
                      to={rev.exposed.average_paid_paise}
                      format={(v) => rupees(Math.round(v))}
                    />
                  </span>
                </div>
              </div>
            </Reveal>

            <Reveal delay={0.14}>
              <div className="stats">
                <div className="stat">
                  <b>
                    <Counter
                      to={rev.extra_paid_per_order_paise}
                      format={(v) => rupees(Math.round(v))}
                    />
                  </b>
                  <span>
                    overpaid on every order, when the seller can see your budget
                  </span>
                </div>
                {lat && (
                  <div className="stat">
                    <b>
                      <Counter
                        to={lat.p50_ms}
                        format={(v) => `${v.toFixed(3)} ms`}
                      />
                    </b>
                    <span>
                      median time to decide, over {lat.samples.toLocaleString()}{" "}
                      runs
                    </span>
                  </div>
                )}
                {bench && (
                  <div className="stat">
                    <b>
                      <Counter
                        to={bench.cases}
                        format={(v) => Math.round(v).toLocaleString()}
                      />
                    </b>
                    <span>
                      benchmark cases, reported separately from the held-out set
                    </span>
                  </div>
                )}
              </div>
            </Reveal>

            {bench && (
              <Reveal delay={0.16}>
                <div className="note">
                  <b>What the numbers are, and are not</b>
                  The {bench.cases.toLocaleString()}-case set was generated in
                  this repository. A test walks the import graph to prove the
                  generator cannot see the policy engine, and a hand-labelled
                  set of 100 is held back and has never been scored. Even so, a
                  perfect score on synthetic data shows the engine and the
                  generator read the specification the same way, not that the
                  engine is right. Every figure here is read from the files
                  those runs wrote.
                </div>
              </Reveal>
            )}
          </div>
        </section>
      )}

      <section className="closer">
        <div className="wrap closer-in">
          <Reveal>
            <h2>Try to make it buy the wrong thing.</h2>
            <p>
              Pick a dishonest seller and watch the gate take its offer apart.
            </p>
          </Reveal>
          <Reveal delay={0.1}>
            <button className="btn btn-primary" onClick={onStart}>
              Start shopping
            </button>
          </Reveal>
        </div>
      </section>

      <footer className="foot wrap">
        Test mode throughout. No live keys, and no real money moves.
      </footer>
    </div>
  );
}
