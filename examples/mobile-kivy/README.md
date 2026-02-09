# Weather – Kivy Mobile App

A simple weather info app built with Kivy for Android.

```yaml markpact:target
platform: mobile
framework: kivy
app_name: WeatherApp
app_id: com.pactown.weather
targets:
  - android
```

```python markpact:file path=main.py
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
import json
import urllib.request


class WeatherApp(App):
    def build(self):
        self.title = "Weather"
        layout = BoxLayout(orientation="vertical", padding=20, spacing=10)

        self.city_input = TextInput(
            hint_text="Enter city name...",
            size_hint_y=0.1,
            multiline=False,
            font_size=20,
        )
        layout.add_widget(self.city_input)

        btn = Button(
            text="Get Weather",
            size_hint_y=0.1,
            font_size=20,
            background_color=(0, 0.48, 1, 1),
        )
        btn.bind(on_press=self.fetch_weather)
        layout.add_widget(btn)

        self.result_label = Label(
            text="Enter a city and tap Get Weather",
            font_size=24,
            halign="center",
            valign="middle",
        )
        self.result_label.bind(size=self.result_label.setter("text_size"))
        layout.add_widget(self.result_label)

        return layout

    def fetch_weather(self, _instance):
        city = self.city_input.text.strip()
        if not city:
            self.result_label.text = "Please enter a city name"
            return

        try:
            url = f"https://wttr.in/{city}?format=j1"
            req = urllib.request.Request(url, headers={"User-Agent": "WeatherApp/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            current = data.get("current_condition", [{}])[0]
            temp_c = current.get("temp_C", "?")
            desc = current.get("weatherDesc", [{}])[0].get("value", "?")
            humidity = current.get("humidity", "?")
            wind = current.get("windspeedKmph", "?")

            self.result_label.text = (
                f"[b]{city}[/b]\n\n"
                f"🌡 {temp_c}°C\n"
                f"☁ {desc}\n"
                f"💧 Humidity: {humidity}%\n"
                f"💨 Wind: {wind} km/h"
            )
            self.result_label.markup = True
        except Exception as e:
            self.result_label.text = f"Error: {e}"


if __name__ == "__main__":
    WeatherApp().run()
```

```python markpact:deps
kivy
buildozer
```

```bash markpact:build
buildozer android debug
```

```bash markpact:run
python main.py
```
