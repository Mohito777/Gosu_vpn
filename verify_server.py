#!/usr/bin/env python3
"""
Simple HTTP server for payment gateway verification files.
Runs on port 80 and serves verification HTML files.
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import os

PORT = 8081
VERIFY_DIR = "/opt/vpn_bot"

class VerificationHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        # Serve only verification files
        if self.path == "/enot_7af5b0ae.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"enot-verify")
        elif self.path == "/lava-verify_0813722c8e674ff6.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"lava-verify=0813722c8e674ff6")
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        print(f"[Verification Server] {args[0]}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), VerificationHandler)
    print(f"🔐 Verification server started on port {PORT}")
    print(f"📄 Files available:")
    print(f"   http://your-domain.com/enot_7af5b0ae.html")
    print(f"   http://your-domain.com/lava-verify_0813722c8e674ff6.html")
    server.serve_forever()
