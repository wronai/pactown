# Web Frontend

Modern web frontend for the SaaS platform. Built with vanilla HTML/CSS/JS with API integration.

## Features

- User dashboard
- API integration
- Real-time stats display
- Responsive design

## Environment Variables

- `API_URL` – API service URL (injected by pactown)
- `MARKPACT_PORT` – Service port (default: 8002)

---

```html markpact:file path=public/index.html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SaaS Platform</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    <style>
        :root { --pico-font-size: 16px; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin: 2rem 0; }
        .stat-card { background: var(--pico-card-background-color); padding: 1.5rem; border-radius: 8px; text-align: center; }
        .stat-value { font-size: 2.5rem; font-weight: bold; color: var(--pico-primary); }
        .stat-label { color: var(--pico-muted-color); margin-top: 0.5rem; }
        .user-list { margin-top: 2rem; }
        .user-item { display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid var(--pico-muted-border-color); }
        .status-indicator { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 0.5rem; }
        .status-ok { background: #22c55e; }
        .status-error { background: #ef4444; }
        header { margin-bottom: 2rem; }
        .actions { display: flex; gap: 1rem; margin: 1rem 0; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <nav>
                <ul><li><strong>🏘️ SaaS Platform</strong></li></ul>
                <ul>
                    <li><span class="status-indicator" id="api-status"></span> API</li>
                    <li><a href="#users">Users</a></li>
                    <li><a href="#stats">Stats</a></li>
                </ul>
            </nav>
        </header>

        <main>
            <section id="stats">
                <h2>Dashboard</h2>
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-value" id="total-users">-</div>
                        <div class="stat-label">Total Users</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="active-services">-</div>
                        <div class="stat-label">Active Services</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="uptime">-</div>
                        <div class="stat-label">Uptime</div>
                    </div>
                </div>
            </section>

            <section id="users">
                <h2>Users</h2>
                <div class="actions">
                    <button id="refresh-btn" class="secondary">🔄 Refresh</button>
                    <button id="add-user-btn">➕ Add User</button>
                </div>
                
                <dialog id="add-user-dialog">
                    <article>
                        <header>Add New User</header>
                        <form id="add-user-form">
                            <label>Name <input type="text" name="name" required></label>
                            <label>Email <input type="email" name="email" required></label>
                            <footer>
                                <button type="button" class="secondary" onclick="document.getElementById('add-user-dialog').close()">Cancel</button>
                                <button type="submit">Create</button>
                            </footer>
                        </form>
                    </article>
                </dialog>

                <div class="user-list" id="user-list">
                    <p>Loading users...</p>
                </div>
            </section>
        </main>

        <footer>
            <p><small>Powered by <a href="https://github.com/wronai/pactown">Pactown</a> + <a href="https://github.com/wronai/markpact">Markpact</a></small></p>
        </footer>
    </div>

    <script>
        const API_URL = window.API_URL || 'http://localhost:8001';

        async function checkApiHealth() {
            const indicator = document.getElementById('api-status');
            try {
                const res = await fetch(`${API_URL}/health`);
                indicator.className = res.ok ? 'status-indicator status-ok' : 'status-indicator status-error';
            } catch {
                indicator.className = 'status-indicator status-error';
            }
        }

        async function loadStats() {
            try {
                const res = await fetch(`${API_URL}/api/stats`);
                const data = await res.json();
                document.getElementById('total-users').textContent = data.total_users;
                document.getElementById('active-services').textContent = data.active_services;
                document.getElementById('uptime').textContent = formatUptime(data.uptime_seconds);
            } catch (e) {
                console.error('Failed to load stats:', e);
            }
        }

        async function loadUsers() {
            const list = document.getElementById('user-list');
            try {
                const res = await fetch(`${API_URL}/api/users`);
                const data = await res.json();
                
                if (data.users.length === 0) {
                    list.innerHTML = '<p>No users yet. Click "Add User" to create one.</p>';
                    return;
                }

                list.innerHTML = data.users.map(user => `
                    <div class="user-item">
                        <div>
                            <strong>${user.name}</strong>
                            <br><small>${user.email}</small>
                        </div>
                        <button class="secondary" onclick="deleteUser(${user.id})">🗑️</button>
                    </div>
                `).join('');
            } catch (e) {
                list.innerHTML = '<p>Failed to load users. Is the API running?</p>';
            }
        }

        async function addUser(name, email) {
            try {
                await fetch(`${API_URL}/api/users`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, email })
                });
                loadUsers();
                loadStats();
            } catch (e) {
                alert('Failed to add user');
            }
        }

        async function deleteUser(id) {
            if (!confirm('Delete this user?')) return;
            try {
                await fetch(`${API_URL}/api/users/${id}`, { method: 'DELETE' });
                loadUsers();
                loadStats();
            } catch (e) {
                alert('Failed to delete user');
            }
        }

        function formatUptime(seconds) {
            if (seconds < 60) return `${Math.floor(seconds)}s`;
            if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
            return `${Math.floor(seconds / 3600)}h`;
        }

        // Event listeners
        document.getElementById('refresh-btn').addEventListener('click', () => {
            loadUsers();
            loadStats();
            checkApiHealth();
        });

        document.getElementById('add-user-btn').addEventListener('click', () => {
            document.getElementById('add-user-dialog').showModal();
        });

        document.getElementById('add-user-form').addEventListener('submit', (e) => {
            e.preventDefault();
            const form = e.target;
            addUser(form.name.value, form.email.value);
            form.reset();
            document.getElementById('add-user-dialog').close();
        });

        // Initial load
        checkApiHealth();
        loadStats();
        loadUsers();
        setInterval(checkApiHealth, 5000);
    </script>
</body>
</html>
```

```python markpact:file path=server.py
import os
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

BASE_DIR = Path(__file__).parent
PUBLIC_DIR = BASE_DIR / "public"

class CORSHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)
    
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
            index_path = PUBLIC_DIR / "index.html"
            if index_path.exists():
                content = index_path.read_text()
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
    print(f'Web server running on http://0.0.0.0:{port}')
    print(f'Serving from: {PUBLIC_DIR}')
    server = HTTPServer(('0.0.0.0', port), CORSHandler)
    server.serve_forever()
```

```bash markpact:run
python server.py
```

```http markpact:test
GET /health EXPECT 200
GET / EXPECT 200
```
