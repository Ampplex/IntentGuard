"""Reading credentials from the environment.

The secret is loaded once, on the server, and there is no code path that puts it
into a response. The key id is public by design -- Razorpay's checkout script
needs it in the browser -- so it is served to the page rather than baked into
it, which keeps the page identical between test and live and keeps the
credential in one place.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field

from ..core.base import StrictModel
from ..payments.razorpay import TEST_KEY_PREFIX, LiveKeyRefused

ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def load_env(path: Path = ENV_PATH) -> None:
    """Read a .env file without adding a dependency for it.

    Values already in the environment win, so a deployment that sets real
    variables is never overridden by a file someone left on disk.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


class Credentials(StrictModel):
    key_id: str
    key_secret: str = Field(repr=False)

    def public(self) -> dict[str, str]:
        """What the browser is allowed to see. The secret is not in it."""
        return {"key_id": self.key_id}


def credentials() -> Credentials:
    """Load and check. A live key is refused here rather than at the first charge."""
    load_env()
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        raise RuntimeError(
            "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set. "
            "Copy .env.example to .env and fill it in."
        )
    if not key_id.startswith(TEST_KEY_PREFIX):
        raise LiveKeyRefused(
            f"key id must begin with {TEST_KEY_PREFIX!r}; this project is test mode only"
        )
    return Credentials(key_id=key_id, key_secret=key_secret)
