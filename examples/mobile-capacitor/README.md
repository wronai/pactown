# Todo List – Capacitor Mobile App

A mobile todo-list app built with Capacitor + vanilla JS.

```yaml markpact:target
platform: mobile
framework: capacitor
app_name: TodoList
app_id: com.pactown.todolist
targets:
  - android
  - ios
```

```html markpact:file path=dist/index.html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Todo List</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, sans-serif; background: #f5f5f5; padding: 20px; }
    h1 { text-align: center; margin-bottom: 20px; color: #333; }
    .input-row { display: flex; gap: 8px; margin-bottom: 16px; }
    input { flex: 1; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; }
    button { padding: 12px 20px; background: #007aff; color: #fff; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; }
    button:active { background: #005ecb; }
    ul { list-style: none; }
    li { display: flex; align-items: center; gap: 12px; padding: 12px; background: #fff; border-radius: 8px; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    li.done span { text-decoration: line-through; color: #999; }
    li span { flex: 1; font-size: 16px; }
    li button { background: #ff3b30; padding: 8px 12px; font-size: 14px; }
    .check { width: 24px; height: 24px; cursor: pointer; }
  </style>
</head>
<body>
  <h1>📝 Todo List</h1>
  <div class="input-row">
    <input id="input" placeholder="Add a task..." />
    <button onclick="addTodo()">Add</button>
  </div>
  <ul id="list"></ul>
  <script>
    let todos = JSON.parse(localStorage.getItem('todos') || '[]');

    function render() {
      const list = document.getElementById('list');
      list.innerHTML = todos.map((t, i) => `
        <li class="${t.done ? 'done' : ''}">
          <input type="checkbox" class="check" ${t.done ? 'checked' : ''} onchange="toggle(${i})">
          <span>${t.text}</span>
          <button onclick="remove(${i})">✕</button>
        </li>
      `).join('');
      localStorage.setItem('todos', JSON.stringify(todos));
    }

    function addTodo() {
      const input = document.getElementById('input');
      const text = input.value.trim();
      if (!text) return;
      todos.push({ text, done: false });
      input.value = '';
      render();
    }

    function toggle(i) { todos[i].done = !todos[i].done; render(); }
    function remove(i) { todos.splice(i, 1); render(); }

    document.getElementById('input').addEventListener('keydown', e => {
      if (e.key === 'Enter') addTodo();
    });

    render();
  </script>
</body>
</html>
```

```javascript markpact:deps
@capacitor/core
@capacitor/cli
```

```bash markpact:build
npx cap sync && npx cap build android
```

```bash markpact:run
npx cap run android
```
