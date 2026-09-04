// Every call here reaches the real backend. There is no fixture path and no
// stubbed response: extraction runs on Bedrock, negotiation runs the actual
// buyer and merchant agents, and an order is created against Razorpay's
// test-mode API. A demo that fakes any of that is a demo of nothing.

async function call(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  // A refusal is an answer, not a failure. 409 carries the violations that
  // explain it, so it is returned rather than thrown.
  if (!response.ok && response.status !== 409) {
    throw new Error(payload.detail || `${path} failed with ${response.status}`);
  }
  return { status: response.status, payload };
}

export const getConfig = () => call("/api/config").then((r) => r.payload);
export const getCatalog = () => call("/api/catalog").then((r) => r.payload);
export const extract = (instruction) =>
  call("/api/extract", { instruction }).then((r) => r.payload);
export const negotiate = (ledger, hostility, concession) =>
  call("/api/negotiate", { ledger, hostility, concession }).then((r) => r.payload);
export const createOrder = (ledger, offer, negotiatedProduct) =>
  call("/api/create-order", {
    ledger,
    offer,
    negotiated_product: negotiatedProduct,
  });
export const verifyPayment = (response) =>
  call("/api/verify-payment", {
    razorpay_order_id: response.razorpay_order_id,
    razorpay_payment_id: response.razorpay_payment_id,
    razorpay_signature: response.razorpay_signature,
  });
