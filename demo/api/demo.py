"""Vercel Python Function; also used by the local HTTP server."""
from http.server import BaseHTTPRequestHandler
import json
from demo_service import run_request
from live_service import live_request, LiveError

MAX_BODY = 65536

class handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, value, status=200):
        raw = json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.send_json(run_request({}))

    def do_POST(self):
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            return self.send_json({'error': 'JSON requests only'}, 415)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= MAX_BODY:
                return self.send_json({'error': 'Request exceeds demonstration limit'}, 413)
            payload = json.loads(self.rfile.read(size))
            self.send_json(live_request(payload) if isinstance(payload,dict) and payload.get('mode')=='live' else run_request(payload))
        except LiveError as exc:
            self.send_json({'error':str(exc)},exc.status)
        except (ValueError, TypeError, KeyError, UnicodeError):
            self.send_json({'error': 'That action is unavailable in the current example. Check the pending proposal or start a new example.'}, 400)
