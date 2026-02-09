# Calculator – Electron Desktop App

A simple calculator built as a desktop application using Electron.

```yaml markpact:target
platform: desktop
framework: electron
app_name: Calculator
app_id: com.pactown.calculator
window_width: 400
window_height: 600
```

```html markpact:file path=index.html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Calculator</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #1c1c1e; color: #fff; }
    #display { width: 100%; padding: 20px; text-align: right; font-size: 48px; background: #1c1c1e; color: #fff; min-height: 100px; }
    .buttons { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; }
    button { padding: 20px; font-size: 24px; border: none; cursor: pointer; background: #2c2c2e; color: #fff; }
    button:hover { background: #3a3a3c; }
    button.operator { background: #ff9500; }
    button.operator:hover { background: #ffb340; }
    button.equals { background: #ff9500; }
    button.clear { background: #a5a5a5; color: #000; }
  </style>
</head>
<body>
  <div id="display">0</div>
  <div class="buttons">
    <button class="clear" onclick="clearDisplay()">C</button>
    <button onclick="appendToDisplay('(')">(</button>
    <button onclick="appendToDisplay(')')">)</button>
    <button class="operator" onclick="appendToDisplay('/')">/</button>
    <button onclick="appendToDisplay('7')">7</button>
    <button onclick="appendToDisplay('8')">8</button>
    <button onclick="appendToDisplay('9')">9</button>
    <button class="operator" onclick="appendToDisplay('*')">×</button>
    <button onclick="appendToDisplay('4')">4</button>
    <button onclick="appendToDisplay('5')">5</button>
    <button onclick="appendToDisplay('6')">6</button>
    <button class="operator" onclick="appendToDisplay('-')">−</button>
    <button onclick="appendToDisplay('1')">1</button>
    <button onclick="appendToDisplay('2')">2</button>
    <button onclick="appendToDisplay('3')">3</button>
    <button class="operator" onclick="appendToDisplay('+')">+</button>
    <button onclick="appendToDisplay('0')">0</button>
    <button onclick="appendToDisplay('.')">.</button>
    <button onclick="deleteLast()">⌫</button>
    <button class="equals" onclick="calculate()">=</button>
  </div>
  <script>
    let display = document.getElementById('display');
    let current = '0';

    function appendToDisplay(val) {
      if (current === '0' && val !== '.') current = '';
      current += val;
      display.textContent = current;
    }
    function clearDisplay() { current = '0'; display.textContent = '0'; }
    function deleteLast() {
      current = current.slice(0, -1) || '0';
      display.textContent = current;
    }
    function calculate() {
      try { current = String(eval(current)); display.textContent = current; }
      catch { display.textContent = 'Error'; current = '0'; }
    }
  </script>
</body>
</html>
```

```javascript markpact:deps
electron
```

```bash markpact:build
npx electron-builder --linux
```

```bash markpact:run
npx electron .
```
