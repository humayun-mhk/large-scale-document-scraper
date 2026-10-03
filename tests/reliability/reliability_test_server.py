from http.server import BaseHTTPRequestHandler, HTTPServer

COUNTERS = {
    "/retry503.pdf": 0,
    "/retry429.pdf": 0,
}

PDF_BYTES = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog >>
endobj
trailer
<<>>
%%EOF
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(format % args)

    def do_GET(self):
        if self.path == "/retry503.pdf":
            COUNTERS[self.path] += 1
            if COUNTERS[self.path] <= 2:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"temporary failure")
                return

        elif self.path == "/retry429.pdf":
            COUNTERS[self.path] += 1
            if COUNTERS[self.path] <= 1:
                self.send_response(429)
                self.send_header("Retry-After", "2")
                self.end_headers()
                self.wfile.write(b"rate limited")
                return

        elif self.path == "/always500.pdf":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"permanent test failure")
            return

        else:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(PDF_BYTES)))
        self.end_headers()
        self.wfile.write(PDF_BYTES)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8765), Handler)
    print("Reliability test server: http://127.0.0.1:8765")
    print("Press Ctrl+C to stop.")
    server.serve_forever()
