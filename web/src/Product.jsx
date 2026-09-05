// Product artwork, drawn per product rather than per category.
//
// The first version drew one picture per category, and the shop showed three
// identical shoes for three different shoes -- which reads as a placeholder,
// because it is one. These are drawn per SKU, filled rather than outlined, and
// coloured from the catalogue's own colour field where it has one.
//
// Why not photographs: the honest options were a stock-photo host, which is an
// external dependency that empties the shop when it rate-limits, or pictures of
// real branded goods, which are not ours to use. Illustration is the option
// that is both reliable and ours.

const GROUND = {
  footwear: "#eef2f8",
  electronics: "#eceff4",
  books: "#f6f1e8",
  apparel: "#f7eff0",
  home_kitchen: "#eaf3ee",
  sports: "#eef2f8",
  beauty: "#f9eef1",
  accessories: "#eef0f4",
  grocery: "#eaf3ee",
  toys: "#f7f0e6",
};

/** Body, shadow and detail tones for a product. */
const SKIN = {
  sku_shoe_01: ["#305eff", "#1e3fb8", "#ffffff"],
  sku_shoe_02: ["#28313d", "#151b24", "#f0263c"],
  sku_shoe_03: ["#8a5a34", "#5f3c21", "#3c2614"],
  sku_lap_01: ["#8e99a8", "#5f6b7a", "#2b323c"],
  sku_lap_02: ["#3a4049", "#22272e", "#f0263c"],
  sku_aud_01: ["#2b323c", "#171c23", "#ffffff"],
  sku_bok_01: ["#b4451f", "#8a3315", "#f6e8d8"],
  sku_bok_02: ["#40566d", "#2b3b4d", "#f8fafc"],
  sku_app_01: ["#f4f6f8", "#d6dde5", "#8e99a8"],
  sku_hom_01: ["#c3ccd6", "#8e99a8", "#40566d"],
  sku_spo_01: ["#c08a4a", "#96682f", "#7a5222"],
  sku_bea_01: ["#e8a23c", "#c17c1c", "#f6e0bd"],
  sku_acc_01: ["#3f4d61", "#293446", "#8e99a8"],
  sku_gro_01: ["#16794a", "#0e5433", "#e7f4ee"],
  sku_toy_01: ["#b07b3e", "#8a5c28", "#f4ead9"],
};

/** A soft contact shadow, which is most of what makes a drawing sit on a surface. */
function Shadow() {
  return <ellipse cx="50" cy="76" rx="27" ry="4.5" fill="rgba(25,40,57,.13)" />;
}

function Drawing({ id, body, dark, detail }) {
  switch (id) {
    case "sku_shoe_01": // Asics Gel-Contend 9 -- low running shoe
    case "sku_shoe_02": // Nike Revolution 7
      return (
        <>
          <Shadow />
          <path
            d="M18 62c0-9 3-15 8-19l9-7 6 8 10 4 20 6c5 1.5 8 4 8 8v2H21a3 3 0 0 1-3-2Z"
            fill={body}
          />
          <path d="M18 66h61v3a3 3 0 0 1-3 3H21a3 3 0 0 1-3-3Z" fill={dark} />
          <path
            d="M35 36l6 8 10 4"
            stroke={detail}
            strokeWidth="3"
            fill="none"
            strokeLinecap="round"
          />
          <path
            d="M45 52l14 5"
            stroke={detail}
            strokeWidth="2.5"
            fill="none"
            strokeLinecap="round"
            opacity=".8"
          />
        </>
      );
    case "sku_shoe_03": // Leather Chelsea Boots -- tall shaft
      return (
        <>
          <Shadow />
          <path d="M33 20h20v34l14 6c5 2 7 4 7 8v3H33Z" fill={body} />
          <path d="M33 66h41v3a3 3 0 0 1-3 3H36a3 3 0 0 1-3-3Z" fill={dark} />
          <rect
            x="53"
            y="26"
            width="5"
            height="24"
            rx="2.5"
            fill={detail}
            opacity=".55"
          />
        </>
      );
    case "sku_lap_01": // Lenovo IdeaPad
    case "sku_lap_02": // ThinkPad T480
      return (
        <>
          <Shadow />
          <path
            d="M24 24h52a3 3 0 0 1 3 3v30H21V27a3 3 0 0 1 3-3Z"
            fill={body}
          />
          <rect x="26" y="29" width="48" height="24" rx="2" fill={dark} />
          <path
            d="M14 57h72l-3 8a3 3 0 0 1-3 2H20a3 3 0 0 1-3-2Z"
            fill={dark}
          />
          <rect
            x="44"
            y="60"
            width="12"
            height="2.5"
            rx="1.25"
            fill={detail}
            opacity=".7"
          />
        </>
      );
    case "sku_aud_01": // boAt Airdopes -- case with buds
      return (
        <>
          <Shadow />
          <rect x="30" y="34" width="40" height="34" rx="9" fill={body} />
          <rect x="30" y="34" width="40" height="9" rx="4.5" fill={dark} />
          <circle cx="41" cy="55" r="6" fill={detail} opacity=".9" />
          <circle cx="59" cy="55" r="6" fill={detail} opacity=".9" />
        </>
      );
    case "sku_bok_01": // Midnight's Children -- hardback
      return (
        <>
          <Shadow />
          <path d="M30 20h36a4 4 0 0 1 4 4v48H34a4 4 0 0 1-4-4Z" fill={body} />
          <rect x="30" y="20" width="7" height="52" fill={dark} />
          <rect x="44" y="34" width="20" height="3" rx="1.5" fill={detail} />
          <rect
            x="44"
            y="42"
            width="14"
            height="2.5"
            rx="1.25"
            fill={detail}
            opacity=".7"
          />
        </>
      );
    case "sku_bok_02": // Ruled Notebook -- spiral
      return (
        <>
          <Shadow />
          <rect x="30" y="20" width="40" height="52" rx="3" fill={body} />
          <rect x="37" y="20" width="33" height="52" fill={detail} />
          <path
            d="M43 32h20M43 40h20M43 48h20M43 56h14"
            stroke={dark}
            strokeWidth="2"
            strokeLinecap="round"
            opacity=".5"
          />
          <circle cx="34" cy="28" r="2.4" fill={dark} />
          <circle cx="34" cy="40" r="2.4" fill={dark} />
          <circle cx="34" cy="52" r="2.4" fill={dark} />
          <circle cx="34" cy="64" r="2.4" fill={dark} />
        </>
      );
    case "sku_app_01": // Cotton T-Shirt
      return (
        <>
          <Shadow />
          <path
            d="M38 22l12 6 12-6 16 9-6 12-6-3v32H34V40l-6 3-6-12Z"
            fill={body}
          />
          <path
            d="M38 22l12 6 12-6"
            stroke={dark}
            strokeWidth="2.5"
            fill="none"
            strokeLinejoin="round"
          />
          <path d="M34 66h32v6H34Z" fill={dark} opacity=".45" />
        </>
      );
    case "sku_hom_01": // Electric Kettle
      return (
        <>
          <Shadow />
          <path
            d="M32 34h30v26a10 10 0 0 1-10 10H42a10 10 0 0 1-10-10Z"
            fill={body}
          />
          <path d="M62 40h6a8 8 0 0 1 0 16h-6Z" fill={dark} />
          <path
            d="M36 34l5-10h13"
            stroke={dark}
            strokeWidth="3"
            fill="none"
            strokeLinecap="round"
          />
          <rect
            x="30"
            y="66"
            width="34"
            height="5"
            rx="2.5"
            fill={detail}
            opacity=".6"
          />
        </>
      );
    case "sku_spo_01": // Cork Yoga Mat -- rolled
      return (
        <>
          <Shadow />
          <rect x="20" y="34" width="58" height="32" rx="16" fill={body} />
          <circle cx="36" cy="50" r="16" fill={dark} />
          <circle cx="36" cy="50" r="7" fill={detail} />
        </>
      );
    case "sku_bea_01": // Vitamin C Serum -- dropper bottle
      return (
        <>
          <Shadow />
          <rect x="40" y="34" width="20" height="36" rx="5" fill={body} />
          <rect x="44" y="20" width="12" height="14" rx="3" fill={dark} />
          <rect
            x="43"
            y="44"
            width="14"
            height="16"
            rx="2"
            fill={detail}
            opacity=".85"
          />
        </>
      );
    case "sku_acc_01": // Laptop Backpack
      return (
        <>
          <Shadow />
          <path
            d="M28 34a14 14 0 0 1 14-14h16a14 14 0 0 1 14 14v30a6 6 0 0 1-6 6H34a6 6 0 0 1-6-6Z"
            fill={body}
          />
          <path d="M28 46h44v10H28Z" fill={dark} />
          <path
            d="M42 20a8 8 0 0 1 16 0"
            stroke={detail}
            strokeWidth="3"
            fill="none"
            strokeLinecap="round"
          />
        </>
      );
    case "sku_gro_01": // Whey Protein -- tub
      return (
        <>
          <Shadow />
          <path d="M32 30h36v34a8 8 0 0 1-8 8H40a8 8 0 0 1-8-8Z" fill={body} />
          <rect x="30" y="20" width="40" height="11" rx="4" fill={dark} />
          <rect
            x="38"
            y="42"
            width="24"
            height="14"
            rx="2"
            fill={detail}
            opacity=".9"
          />
        </>
      );
    case "sku_toy_01": // Wooden Chess Set -- king and pawn
      return (
        <>
          <Shadow />
          <path d="M44 24h6v-5h4v5h6l-4 10 3 22h-14l3-22Z" fill={body} />
          <path
            d="M40 56h26l4 10a3 3 0 0 1-3 4H39a3 3 0 0 1-3-4Z"
            fill={dark}
          />
          <circle cx="30" cy="46" r="6" fill={body} />
          <path d="M24 56h12l2 8H22Z" fill={dark} />
          <rect
            x="46"
            y="40"
            width="8"
            height="3"
            rx="1.5"
            fill={detail}
            opacity=".7"
          />
        </>
      );
    default:
      return (
        <>
          <Shadow />
          <rect x="28" y="28" width="44" height="38" rx="4" fill={body} />
          <path
            d="M28 56l12-10 9 7 7-6 16 12v3a4 4 0 0 1-4 4H32a4 4 0 0 1-4-4Z"
            fill={dark}
          />
          <circle cx="41" cy="40" r="4.5" fill={detail} />
        </>
      );
  }
}

export function ProductImage({ product }) {
  const [body, dark, detail] = SKIN[product.product_id] ?? [
    "#8e99a8",
    "#5f6b7a",
    "#f8fafc",
  ];
  return (
    <div
      className="thumb"
      style={{ background: GROUND[product.category] ?? "#eef0f4" }}
    >
      <svg viewBox="0 0 100 84" role="img" aria-label={product.title}>
        <Drawing
          id={product.product_id}
          body={body}
          dark={dark}
          detail={detail}
        />
      </svg>
    </div>
  );
}

export const CATEGORY_LABEL = {
  footwear: "Footwear",
  electronics: "Electronics",
  books: "Books",
  apparel: "Apparel",
  home_kitchen: "Home & Kitchen",
  sports: "Sports",
  beauty: "Beauty",
  accessories: "Accessories",
  grocery: "Grocery",
  toys: "Toys",
};
