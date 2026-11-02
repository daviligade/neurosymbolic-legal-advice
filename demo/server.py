"""Local development server: python3 server.py --port 8766."""
import argparse
import os
import json
import importlib
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from api.demo import handler as ApiHandler

PUBLIC = Path(__file__).parent / 'public'
FILES = {'/': ('index.html', 'text/html; charset=utf-8'),
         '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
         '/style.css': ('style.css', 'text/css; charset=utf-8'),
         '/libra-advice-mark.svg': ('libra-advice-mark.svg', 'image/svg+xml')}

# Local development reload retains the in-memory credential and session signer.
# It is absent from the deployed function and accepts no source from requests.
APP_MODULES=('demo_engine','demo_service','live_service','api.demo')
RELOAD_LOCK=threading.Lock()
def app_version():
    return tuple((Path(__file__).parent/(name.replace('.','/')+'.py')).stat().st_mtime_ns for name in APP_MODULES)
APP_VERSION=app_version()
def refresh_application():
    global APP_VERSION
    with RELOAD_LOCK:
        version=app_version()
        if version==APP_VERSION:return
        import live_service
        signer=live_service.LOCAL_SECRET
        for name in APP_MODULES:importlib.reload(importlib.import_module(name))
        live_service.LOCAL_SECRET=signer
        APP_VERSION=version

class Handler(ApiHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/demo':
            return super().do_GET()
        if path not in FILES:
            return self.send_json({'error': 'Not found'}, 404)
        name, mime = FILES[path]; raw = (PUBLIC / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers(); self.wfile.write(raw)

    def do_POST(self):
        # Local development only. This route is absent from api/demo.py on Vercel.
        if urlparse(self.path).path == '/_local/configure-groq':
            if (self.client_address[0] != '127.0.0.1' or self.headers.get('Origin')
                    or self.headers.get('X-Libra-Local-Setup') != 'hidden-prompt'
                    or self.headers.get('Content-Type') != 'application/json'):
                return self.send_json({'error':'Local setup only'},403)
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 2048: raise ValueError()
                values = json.loads(self.rfile.read(size))
                key = values.get('api_key','')
                if not isinstance(key,str) or not key.startswith('gsk_') or not 20 < len(key) < 512: raise ValueError()
                if values.get('free_tier_confirmed') is not True: raise ValueError()
                os.environ['GROQ_API_KEY'] = key
                os.environ['GROQ_FREE_TIER_CONFIRMED'] = '1'
                return self.send_json({'configured':True})
            except (ValueError,TypeError,UnicodeError):
                return self.send_json({'error':'A Groq key and confirmation of the Free plan are required.'},400)
        if urlparse(self.path).path != '/api/demo':
            return self.send_json({'error': 'Not found'}, 404)
        refresh_application()
        return super().do_POST()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        print(f'Demo: http://127.0.0.1:{args.port}', flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: pass
