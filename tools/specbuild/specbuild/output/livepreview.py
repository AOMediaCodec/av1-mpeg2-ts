"""Live preview HTTP server for spec development.

Serves the built HTML output on localhost and pairs with ``--watch`` to
provide instant visual feedback on source changes.  Adds three things on
top of a plain ``SimpleHTTPRequestHandler``:

* ``Cache-Control: no-store`` on every response — prevents the browser
  from caching dev artifacts between rebuilds.
* A Server-Sent Events endpoint at ``/__specbuild/events`` — the watch
  loop calls :func:`notify_reload` after each successful rebuild, which
  pushes a ``reload`` event to every connected client.
* Inline injection into served HTML — a tiny client snippet that
  unregisters any leftover service worker (in case a prior PWA build
  left one registered for this origin) and listens to the SSE channel
  to ``location.reload()`` on rebuild.
"""

from __future__ import annotations

import logging
import queue
import socket
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
# Reload broadcast — registered SSE clients
# ---------------------------------------------------------------------------

_clients: set[queue.Queue[str]] = set()
_clients_lock = threading.Lock()


def notify_reload() -> None:
    """Push a reload event to every connected SSE client.

    Called by the watch loop after a successful rebuild.  Cheap and
    idempotent: a queue per browser tab, drained by the SSE handler.
    """
    with _clients_lock:
        n = len(_clients)
        for q in _clients:
            try:
                q.put_nowait("reload")
            except queue.Full:
                pass
    if n:
        logging.info(f"Livereload: notified {n} client(s)")


# ---------------------------------------------------------------------------
# Inline client snippet — injected into every served HTML response
# ---------------------------------------------------------------------------

_RELOAD_SNIPPET = """
<script>
(function () {
  // Unregister any leftover service worker from a prior PWA build.
  // Without this, a cache-first SW would serve stale assets forever.
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.getRegistrations().then(function (regs) {
      regs.forEach(function (r) { r.unregister(); });
    });
  }
  // Listen for rebuild events from the dev server and full-reload.
  try {
    var es = new EventSource('/__specbuild/events');
    es.addEventListener('reload', function () { location.reload(); });
  } catch (e) { /* dev-only; fail silently */ }
})();
</script>
""".strip()


def _inject_reload_snippet(html_bytes: bytes) -> bytes:
    """Insert the livereload snippet before ``</body>`` (or append if missing)."""
    needle = b"</body>"
    idx = html_bytes.rfind(needle)
    snippet = _RELOAD_SNIPPET.encode("utf-8")
    if idx == -1:
        return html_bytes + snippet
    return html_bytes[:idx] + snippet + html_bytes[idx:]


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def find_free_port(preferred: int = 8080) -> int:
    """Return *preferred* if available, otherwise the next free port."""
    for port in range(preferred, preferred + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(
        f"No free port found in range {preferred}–{preferred + 99}. "
        "Free up a port or configure a different starting port."
    )


def start_server(output_dir: Path, port: int = 8080) -> tuple[ThreadingHTTPServer, str]:
    """Start an HTTP server serving *output_dir* in a daemon thread.

    Args:
        output_dir: Directory containing the built HTML to serve.
        port:       Preferred port number; a free port is found if taken.

    Returns:
        ``(httpd, url)`` — the HTTPServer instance and the root URL.
    """
    port = find_free_port(port)

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(output_dir), **kw)

        def log_message(self, fmt, *args):
            logging.debug("HTTP: " + fmt % args)

        def end_headers(self):
            # Force fresh fetch on every request — dev mode.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            super().end_headers()

        def do_GET(self):
            if self.path.split("?", 1)[0] == "/__specbuild/events":
                return self._handle_sse()
            return self._handle_file()

        def _handle_sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                self.wfile.write(b"retry: 1000\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return None

            q: queue.Queue[str] = queue.Queue(maxsize=8)
            with _clients_lock:
                _clients.add(q)
            try:
                while True:
                    try:
                        msg = q.get(timeout=15.0)
                    except queue.Empty:
                        # Keepalive comment so proxies / browsers don't drop us.
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    if msg == "reload":
                        self.wfile.write(b"event: reload\ndata: 1\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                with _clients_lock:
                    _clients.discard(q)
            return None

        def _handle_file(self):
            path = self.translate_path(self.path)
            p = Path(path)
            if p.is_dir():
                for fname in ("index.html", "index.htm"):
                    cand = p / fname
                    if cand.is_file():
                        p = cand
                        break
            if p.is_file() and p.suffix.lower() in (".html", ".htm"):
                try:
                    body = p.read_bytes()
                except OSError:
                    return super().do_GET()
                body = _inject_reload_snippet(body)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Last-Modified", self.date_time_string(int(time.time())))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return None
            return super().do_GET()

    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    # Browsers open speculative TCP connections (Chrome preconnect, etc.) and
    # close them without sending a request — silence the resulting noisy
    # tracebacks while still surfacing real handler errors.
    _orig_handle_error = httpd.handle_error

    def _quiet_handle_error(request, client_address):
        import sys

        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        _orig_handle_error(request, client_address)

    httpd.handle_error = _quiet_handle_error

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    url = f"http://localhost:{port}"
    return httpd, url


def open_browser(url: str) -> None:
    """Open *url* in the default browser (best-effort, no error on failure)."""
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        pass


def find_index_html(output_dir: Path) -> Path | None:
    """Return the main HTML file in *output_dir*, or None."""
    for candidate in ("index.html", "index.htm"):
        p = output_dir / candidate
        if p.exists():
            return p
    html_files = sorted(output_dir.glob("*.html"))
    return html_files[0] if html_files else None
