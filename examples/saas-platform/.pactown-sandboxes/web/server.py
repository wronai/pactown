import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

class CORSHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="public", **kwargs)
    
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "web"}')
            return
        
        # Inject API_URL into index.html
        if self.path == '/' or self.path == '/index.html':
            api_url = os.environ.get('API_URL', 'http://localhost:8001')
            with open('public/index.html', 'r') as f:
                content = f.read()
            content = content.replace(
                "window.API_URL || 'http://localhost:8001'",
                f"'{api_url}'"
            )
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(content.encode())
            return
        
        super().do_GET()

if __name__ == '__main__':
    port = int(os.environ.get('MARKPACT_PORT', 8002))
    server = HTTPServer(('0.0.0.0', port), CORSHandler)
    print(f'Web server running on http://0.0.0.0:{port}')
    server.serve_forever()