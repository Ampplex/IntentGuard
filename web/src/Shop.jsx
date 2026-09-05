import { useMemo, useState } from "react";
import { CATEGORY_LABEL, ProductImage } from "./Product.jsx";
import { rupees } from "./format";

/** The seller's real shelf, fetched from the API rather than written here. */
export default function Shop({ catalog, onAsk }) {
  const [category, setCategory] = useState("all");

  const categories = useMemo(() => {
    const seen = [];
    for (const item of catalog)
      if (!seen.includes(item.category)) seen.push(item.category);
    return seen;
  }, [catalog]);

  const shown =
    category === "all"
      ? catalog
      : catalog.filter((i) => i.category === category);

  return (
    <div className="wrap">
      <div className="shop-head">
        <div>
          <h1>The shop</h1>
          <p>
            {catalog.length} products, real prices. Ask the agent to buy one and
            watch it get checked before any money moves.
          </p>
        </div>
      </div>

      <div className="filters">
        <button
          className="chip"
          aria-pressed={category === "all"}
          onClick={() => setCategory("all")}
        >
          Everything
        </button>
        {categories.map((c) => (
          <button
            key={c}
            className="chip"
            aria-pressed={category === c}
            onClick={() => setCategory(c)}
          >
            {CATEGORY_LABEL[c] ?? c}
          </button>
        ))}
      </div>

      <div className="catalog">
        {shown.map((item) => (
          <article className="card" key={item.product_id}>
            <ProductImage product={item} />
            <div className="card-body">
              <span className="card-cat">
                {CATEGORY_LABEL[item.category] ?? item.category}
              </span>
              <span className="card-title">{item.title}</span>
              {item.brand && <span className="card-brand">{item.brand}</span>}
              <div className="card-foot">
                <span className="price">{rupees(item.price_paise)}</span>
                <button
                  className="ask"
                  onClick={() =>
                    onAsk(
                      `Buy me a ${item.title}, budget ₹${Math.round(
                        item.price_paise / 100,
                      ).toLocaleString("en-IN")}. No subscriptions.`,
                    )
                  }
                >
                  Ask the agent
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
