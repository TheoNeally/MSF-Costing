"""Dependency-free local HTTP server for the MSF Costing Tool."""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .calculations import calculate_estimate, default_estimate
from .rates import (
    CATEGORIES,
    CONFIDENCE_LABELS,
    CONFIDENCE_LEVELS,
    RateLibrary,
    RateValidationError,
)
from .store import EstimateStore


MAX_BODY_BYTES = 2 * 1024 * 1024


class CostingRequestHandler(BaseHTTPRequestHandler):
    server_version = f"MSFCosting/{__version__}"

    @property
    def app(self) -> "CostingServer":
        return self.server  # type: ignore[return-value]

    def _send_json(self, value: object, status: int = 200) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("Request body is empty or too large")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON request body must be an object")
        return value

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json({"ok": True, "version": __version__})
            return
        if path == "/api/defaults":
            self._send_json(self.app.rates.apply_to(default_estimate()))
            return
        if path == "/api/rates":
            self._send_json(self._rate_library_payload())
            return
        if path == "/api/rates/history":
            query = parse_qs(urlparse(self.path).query)
            rate_path = query.get("path", [None])[0]
            try:
                limit = int(query.get("limit", ["100"])[0])
            except ValueError:
                limit = 100
            self._send_json(
                {"history": self.app.rates.history(limit=limit, path=rate_path)}
            )
            return
        if path == "/api/estimates":
            self._send_json({"estimates": self.app.store.list()})
            return
        if path.startswith("/api/estimates/"):
            record_id = unquote(path.removeprefix("/api/estimates/"))
            record = self.app.store.get(record_id)
            if record is None:
                self._send_json({"error": "Estimate revision not found"}, 404)
            else:
                self._send_json(record)
            return
        if path.startswith("/api/"):
            self._send_json({"error": "API route not found"}, 404)
            return
        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/calculate":
                results = calculate_estimate(body)
                self._send_json(results, 200 if results["ok"] else 422)
                return
            if path == "/api/estimates":
                payload = body.get("payload")
                if not isinstance(payload, dict):
                    raise ValueError("payload must be an object")
                results = calculate_estimate(payload)
                if not results["ok"]:
                    self._send_json(results, 422)
                    return
                project_id = body.get("project_id")
                if project_id is not None and not isinstance(project_id, str):
                    raise ValueError("project_id must be a string")
                record = self.app.store.save(payload, results, project_id)
                self._send_json({"saved": record, "results": results}, 201)
                return
            self._send_json({"error": "API route not found"}, 404)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.log_error("Unhandled request failure: %s", exc)
            self._send_json({"error": "Unexpected server error"}, 500)

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/rates":
                updates = body.get("updates")
                if not isinstance(updates, dict):
                    raise ValueError("updates must be an object")
                changes = self.app.rates.update(
                    updates,
                    changed_by=str(body.get("changed_by") or ""),
                    reason=str(body.get("reason") or ""),
                )
                payload = self._rate_library_payload()
                payload["changes"] = changes
                self._send_json(payload)
                return
            self._send_json({"error": "API route not found"}, 404)
        except RateValidationError as exc:
            self._send_json(
                {"error": "Rate changes were rejected", "details": exc.details},
                HTTPStatus.BAD_REQUEST,
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except OSError as exc:
            self.log_error("Rate library write failed: %s", exc)
            self._send_json({"error": "Could not write the rate library"}, 500)
        except Exception as exc:
            self.log_error("Unhandled request failure: %s", exc)
            self._send_json({"error": "Unexpected server error"}, 500)

    def _rate_library_payload(self) -> dict:
        rates = self.app.rates
        return {
            "library": rates.stamp(),
            "entries": rates.entries(),
            "categories": list(CATEGORIES),
            "confidence_levels": [
                {"value": level, "label": CONFIDENCE_LABELS[level]}
                for level in CONFIDENCE_LEVELS
            ],
            "path": str(rates.path),
            "load_error": rates.load_error,
        }

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else unquote(request_path[1:])
        candidate = (self.app.static_root / relative).resolve()
        try:
            candidate.relative_to(self.app.static_root)
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.is_file():
            candidate = self.app.static_root / "index.html"
        data = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[MSF] {self.address_string()} - {fmt % args}")


class CostingServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        static_root: Path,
        store: EstimateStore,
        rates: RateLibrary,
    ) -> None:
        self.static_root = static_root.resolve()
        self.store = store
        self.rates = rates
        super().__init__(address, CostingRequestHandler)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    root: Path | None = None,
    database_path: Path | None = None,
    rates_path: Path | None = None,
) -> None:
    project_root = root or Path(__file__).resolve().parent.parent
    static_root = project_root / "static"
    store = EstimateStore(database_path or project_root / "data" / "msf_costing.db")
    rates = RateLibrary.load(rates_path or project_root / "rates.json")
    server = CostingServer((host, port), static_root, store, rates)
    url = f"http://{host}:{server.server_port}"
    print(f"MSF Costing Tool {__version__} running at {url}")
    print(f"Rate library: {rates.path} ({rates.stamp()['label']})")
    if rates.load_error:
        print(f"WARNING: {rates.load_error}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping MSF Costing Tool.")
    finally:
        server.server_close()
