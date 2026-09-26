import os
import urllib.parse
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from typing import Tuple

EXTRA_MIME = {
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".apng": "image/png",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


class LocalAssetHandler(BaseHTTPRequestHandler):
    web_dir = ""

    def log_message(self, format, *args):
        # Silence standard HTTP access logging in console
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 1. Image proxy endpoint: /image?path=E%3A%2Fpath%2Fto%2Fimg.png
        if path == "/api/image":
            query = urllib.parse.parse_qs(parsed.query)
            file_path = query.get("path", [""])[0]
            if file_path and os.path.exists(file_path):
                try:
                    mime, _ = mimetypes.guess_type(file_path)
                    ext = os.path.splitext(file_path)[1].lower()
                    mime = EXTRA_MIME.get(ext, mime or "application/octet-stream")
                    file_size = os.path.getsize(file_path)

                    start, end = 0, file_size - 1
                    partial = False
                    range_header = self.headers.get("Range")
                    if range_header and range_header.startswith("bytes="):
                        spec = range_header[len("bytes="):].split(",")[0].strip()
                        lo, _, hi = spec.partition("-")
                        try:
                            if lo:
                                start = int(lo)
                                end = int(hi) if hi else file_size - 1
                            elif hi:                     # suffix range: last N bytes
                                start = max(0, file_size - int(hi))
                                end = file_size - 1
                            start = max(0, min(start, file_size - 1))
                            end = max(start, min(end, file_size - 1))
                            partial = True
                        except ValueError:
                            start, end, partial = 0, file_size - 1, False

                    length = end - start + 1
                    self.send_response(206 if partial else 200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(length))
                    self.send_header("Accept-Ranges", "bytes")
                    if partial:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                    self.send_header("Cache-Control", "max-age=86400")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()

                    with open(file_path, "rb") as f:
                        f.seek(start)
                        remaining = length
                        while remaining > 0:
                            chunk = f.read(min(262144, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    return
                except (BrokenPipeError, ConnectionResetError,
                        ConnectionAbortedError, OSError):
                    # browsers abort video/range streams routinely — not an error
                    return
                except Exception as e:
                    print(f"[Server] image proxy failed: {e}")
                    try:
                        self.send_error(500, "Internal error")
                    except Exception:
                        pass
                    return
            else:
                self.send_error(404, "Image file not found")
                return

        # 2. Static files from web directory
        rel_path = path.lstrip("/")
        if not rel_path or rel_path == "":
            rel_path = "index.html"

        # Sanitize relative path
        safe_path = os.path.normpath(os.path.join(self.web_dir, rel_path))
        if not safe_path.startswith(os.path.normpath(self.web_dir)):
            self.send_error(403, "Access denied")
            return

        if os.path.exists(safe_path) and os.path.isfile(safe_path):
            try:
                mime, _ = mimetypes.guess_type(safe_path)
                mime = mime or "text/plain"
                if safe_path.endswith(".css"):
                    mime = "text/css"
                elif safe_path.endswith(".js"):
                    mime = "application/javascript"
                elif safe_path.endswith(".html"):
                    mime = "text/html; charset=utf-8"

                with open(safe_path, "rb") as f:
                    content = f.read()

                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
                return
            except (BrokenPipeError, ConnectionResetError,
                    ConnectionAbortedError, OSError):
                return
            except Exception as e:
                print(f"[Server] asset failed: {e}")
                try:
                    self.send_error(500, "Internal error")
                except Exception:
                    pass
                return

        self.send_error(404, "File not found")


def start_local_server(web_dir: str) -> Tuple[HTTPServer, int]:
    """Starts a local HTTP server on a random free port."""
    LocalAssetHandler.web_dir = os.path.abspath(web_dir)
    # Bind to 127.0.0.1 on port 0 (OS picks a free port)
    server = HTTPServer(("127.0.0.1", 0), LocalAssetHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port
