# Selection Translator

KDE Plasma 6 panel widget for showing an offline Chinese translation of the selected English word.

Single-word lookup is offline through the bundled ECDICT SQLite database. Multi-word selections are treated as sentence candidates: the widget asks for confirmation first, and only sends text to an online sentence backend after pressing `翻译整句`. The current order is DeepSeek, OpenAI, then Google Translate's public web endpoint.

## Build Dictionary

The widget queries `package/contents/data/ecdict.sqlite3`. Build it from ECDICT:

```sh
curl -L -o vendor/ecdict.csv https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv
python3 scripts/build_ecdict_sqlite.py vendor/ecdict.csv package/contents/data/ecdict.sqlite3
```

## Install

```sh
kpackagetool6 -t Plasma/Applet -u package
```

Then add `Selection Translator` / `划词翻译` to a Plasma panel.

On Wayland, one session D-Bus service owns the selection listeners. It uses `wl-paste --watch` for both the primary selection and clipboard. Widgets read the shared service state through lightweight D-Bus calls; they do not start a Python process or read the clipboard on a timer. Some applications or compositors may not expose selected text globally; copying the word will still update the widget.

The service is started automatically by the first widget instance and remains available for the desktop session. If it exits, any remaining widget instance starts it again.

## Sentence Translation

Sentence translation requires network access and is intentionally manual so selected text is not uploaded automatically.

DeepSeek is preferred when configured. The easiest path is the widget configuration UI: right-click the widget, open settings, and paste the key on the `翻译服务` page.

Environment variables are also supported:

```sh
export DEEPSEEK_API_KEY='sk-...'
export DEEPSEEK_MODEL='deepseek-v4-flash'
```

OpenAI is also supported:

```sh
export OPENAI_API_KEY='sk-...'
export OPENAI_MODEL='gpt-5-nano'
```

or with a config file:

```sh
mkdir -p ~/.config/selection-translator
cp config.example.json ~/.config/selection-translator/config.json
chmod 600 ~/.config/selection-translator/config.json
```

Then edit `~/.config/selection-translator/config.json` and set `deepseek_api_key` or `openai_api_key`. The widget configuration UI takes precedence over this file.

Dictionary data: [ECDICT](https://github.com/skywind3000/ECDICT), MIT License.
