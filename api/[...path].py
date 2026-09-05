"""Vercel's entry point: the same FastAPI application, nothing forked.

A second copy of the app for deployment would be a second place for the rules
to live, and the first one to drift would be the one nobody runs tests against.
The package itself arrives through requirements.txt, which installs this
repository. So this imports the real thing and only adapts the two places where
a serverless host differs from a long-lived server:

- the audit trail goes to a writable scratch directory, which is per-instance
  and does not survive a cold start;
- the catalog's embeddings are warmed lazily rather than on import, because
  fifteen calls before the first response can outlast the invocation.

Both are set as environment defaults here rather than in the application, so
running locally keeps the durable behaviour.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault(
    "INTENTGUARD_AUDIT_PATH", str(Path(tempfile.gettempdir()) / "intentguard-audit.jsonl")
)
os.environ.setdefault("INTENTGUARD_WARM_EMBEDDINGS", "0")

# Named here so the bundler ships them. It decides what to include by tracing
# imports out of this file, and it does not follow imports made inside an
# installed package -- so intentguard arrived without fastapi underneath it and
# the function failed on its first line. These are not used here; they are
# declarations of what the application will reach for.
import boto3  # noqa: E402,F401
import fastapi  # noqa: E402,F401
import pydantic  # noqa: E402,F401

from intentguard.api.app import create_app  # noqa: E402

_app = create_app()


# The routes the application really serves, used to tell "the host mangled the
# path" apart from "this path does not exist".
_KNOWN = {getattr(r, "path", "") for r in _app.routes}


async def app(scope, receive, send):
    """The application, with the host's path handling undone.

    Vercel routes a request into this function by its filename, and what lands
    in the ASGI scope is not the URL the browser asked for: a rewrite made it
    the function's own path, and a catch-all function receives the path with
    its /api prefix already consumed. Either way FastAPI answers 404 for a
    route it really does have, which reads exactly like a broken deployment and
    cost three deploys chasing the wrong cause.

    So the path is restored from whichever source actually has it, and a request
    carrying x-ig-debug reports what arrived rather than guessing again.
    """
    if scope["type"] == "http":
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        received = scope.get("path", "")

        original = (
            headers.get("x-vercel-original-path")
            or headers.get("x-vercel-original-pathname")
            or headers.get("x-rewrite-url")
            or headers.get("x-original-uri")
        )
        resolved = original.partition("?")[0] if original else received

        # A catch-all under api/ is handed the path with its prefix consumed,
        # so "/config" here means "/api/config" to the application.
        if resolved not in _KNOWN and not resolved.startswith("/api/"):
            candidate = "/api" + ("" if resolved.startswith("/") else "/") + resolved
            if candidate in _KNOWN:
                resolved = candidate

        if headers.get("x-ig-debug"):
            body = json.dumps(
                {
                    "path_received": received,
                    "path_resolved": resolved,
                    "original_header": original,
                    "headers_present": sorted(headers),
                    "known_routes": sorted(_KNOWN),
                },
                indent=1,
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [[b"content-type", b"application/json"]],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        if resolved != received:
            scope = {**scope, "path": resolved, "raw_path": resolved.encode()}

    await _app(scope, receive, send)
