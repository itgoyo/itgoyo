"""One-time Spotify OAuth helper. Prints a refresh token for GitHub Actions.

Required env:
    SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET
Redirect URI in the Spotify Dashboard:
    http://127.0.0.1:4180/callback
"""
from __future__ import annotations

import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

REDIRECT_URI = "http://127.0.0.1:4180/callback"
SCOPES = "user-read-currently-playing user-read-recently-played"


def main() -> int:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET first.")
        return 1

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    }
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)
    print("Open this URL if the browser does not start:\n", url)
    webbrowser.open(url)

    code_holder = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            code_holder["code"] = (qs.get("code") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK. You can close this tab.")

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 4180), Handler)
    while "code" not in code_holder:
        server.handle_request()
    server.server_close()

    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": code_holder["code"],
            "redirect_uri": REDIRECT_URI,
        },
        auth=(client_id, client_secret),
        timeout=20,
    )
    resp.raise_for_status()
    token = resp.json().get("refresh_token")
    if not token:
        print("No refresh_token in response.")
        return 1
    print("SPOTIFY_REFRESH_TOKEN=" + token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
