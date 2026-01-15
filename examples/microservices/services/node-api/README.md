# Node.js API Service

REST API service using Node.js and Express. Demonstrates JavaScript service in a polyglot ecosystem.

## Endpoints

- `GET /health` – Health check
- `GET /api/items` – List items
- `POST /api/items` – Create item
- `POST /api/predict` – Proxy to ML service

---

```json markpact:file path=package.json
{
  "name": "node-api-service",
  "version": "1.0.0",
  "type": "module",
  "main": "server.js",
  "scripts": {
    "start": "node server.js"
  },
  "dependencies": {
    "express": "^4.18.2"
  }
}
```

```javascript markpact:file path=server.js
import express from "express";

const app = express();
app.use(express.json());

const port = process.env.MARKPACT_PORT || 3000;
const ML_SERVICE_URL = process.env.ML_SERVICE_URL || "http://localhost:8010";

// In-memory storage
const items = [];
let nextId = 1;

app.get("/health", (req, res) => {
  res.json({ status: "ok", service: "node-api" });
});

app.get("/api/items", (req, res) => {
  res.json({ items, count: items.length });
});

app.post("/api/items", (req, res) => {
  const { name, value } = req.body;
  const item = { id: nextId++, name, value, createdAt: new Date().toISOString() };
  items.push(item);
  res.status(201).json(item);
});

app.get("/api/items/:id", (req, res) => {
  const item = items.find(i => i.id === parseInt(req.params.id));
  if (!item) {
    return res.status(404).json({ error: "Item not found" });
  }
  res.json(item);
});

app.delete("/api/items/:id", (req, res) => {
  const index = items.findIndex(i => i.id === parseInt(req.params.id));
  if (index === -1) {
    return res.status(404).json({ error: "Item not found" });
  }
  items.splice(index, 1);
  res.json({ message: "Deleted" });
});

// Proxy to ML service
app.post("/api/predict", async (req, res) => {
  try {
    const response = await fetch(`${ML_SERVICE_URL}/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req.body),
    });
    const data = await response.json();
    res.json({ ...data, proxied_from: "node-api" });
  } catch (error) {
    res.status(503).json({ error: "ML service unavailable", details: error.message });
  }
});

app.listen(port, "0.0.0.0", () => {
  console.log(`Node API listening on http://0.0.0.0:${port}`);
  console.log(`ML Service URL: ${ML_SERVICE_URL}`);
});
```

```bash markpact:run
npm install
MARKPACT_PORT=${MARKPACT_PORT:-3000} npm start
```

```http markpact:test
GET /health EXPECT 200
GET /api/items EXPECT 200
POST /api/items BODY {"name":"test","value":42} EXPECT 201
```