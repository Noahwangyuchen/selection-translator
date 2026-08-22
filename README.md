# Selection Translator / 划词翻译

KDE Plasma 6 panel widget that displays Chinese translations for selected English text.

Single-word lookup is offline through the bundled ECDICT SQLite database. The expanded word view can optionally request an online translation. Multi-word selections are treated as sentence candidates: the widget asks for confirmation first and only sends text to an online backend after pressing `翻译整句`.

## Features

- Automatic translation of the current primary selection on Wayland and X11.
- Offline dictionary lookup for single English words.
- Optional DeepSeek, OpenAI, and Google Translate backends for sentences and words.
- Configurable online service priority and optional clipboard monitoring.
- One shared D-Bus listener and synchronized results across multiple widget instances.

## Requirements

- KDE Plasma 6
- Python 3 with D-Bus and PyGObject bindings
- Wayland: `wl-clipboard`
- X11: `xclip` or `xsel`

Common package names are `python-dbus`, `python-gobject`, and `wl-clipboard` on Arch Linux; or `python3-dbus`, `python3-gi`, and `wl-clipboard` on Debian-derived distributions.

## Install A Release

Download the `.plasmoid` file from the latest [GitHub Release](https://github.com/Noahwangyuchen/plasma-selection-translator/releases/latest), then run:

```sh
kpackagetool6 -t Plasma/Applet -i selection-translator-0.3.3.plasmoid
```

For an existing installation, replace `-i` with `-u`. Then add `Selection Translator` / `划词翻译` to a Plasma panel.

## GNOME 46

The repository also contains a GNOME Shell 46 panel frontend. It uses the same
Python D-Bus service, offline ECDICT database, privacy rules, and online
translation configuration as the Plasma widget. On X11, the service polls the
PRIMARY selection with `xclip`; on Wayland it keeps the upstream `wl-paste`
listeners. GNOME Wayland may not expose another application's primary selection;
copying the text remains the fallback in that case.

In addition to the common Python D-Bus/PyGObject requirements, install `xclip`
for GNOME X11 or `wl-clipboard` for GNOME Wayland.

After generating or extracting `package/contents/data/ecdict.sqlite3`, install
the GNOME frontend with:

```sh
scripts/install_gnome.sh
gnome-extensions enable selection-translator@noahwangyuchen.local
```

The installer creates a user service and installs the extension under
`~/.local/share/gnome-shell/extensions`. A GNOME Shell restart or a log out/in
may be required the first time the extension is installed. Set `PYTHON_BIN` if
the required `dbus` and `gi` modules are installed in a non-default Python.
Online translation settings are stored in
`~/.config/selection-translator/config.json`.

## Build From Source

The widget queries `package/contents/data/ecdict.sqlite3`. Build it from ECDICT:

```sh
curl -L -o vendor/ecdict.csv https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv
python3 scripts/build_ecdict_sqlite.py vendor/ecdict.csv package/contents/data/ecdict.sqlite3
```

```sh
kpackagetool6 -t Plasma/Applet -u package
```

## How It Works

On Wayland, one session D-Bus service owns the selection listeners. It uses `wl-paste --watch` for both the primary selection and clipboard, then pushes state changes to every widget through D-Bus signals. Widgets do not poll, start a Python process, or read the clipboard on a timer. Some applications or compositors may not expose selected text globally; copying the word will still update the widget.

Clipboard-triggered translation can be disabled from the widget configuration. Primary selections continue to update automatically, while the manual refresh action can still read the current clipboard when needed.

The service is started automatically by the first widget instance and remains available for the desktop session. If it exits, any remaining widget instance starts it again. If either `wl-paste` listener exits unexpectedly, the service restarts that listener automatically.

## Sentence Translation

Sentence translation requires network access and is intentionally manual so selected text is not uploaded automatically.

The easiest setup path is the widget configuration UI: right-click the widget and open the `翻译服务` page. The same page lets you arrange DeepSeek, OpenAI, and Google Translate in the order they should be attempted. Both sentence translation and optional online word translation use that order.

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

Then edit `~/.config/selection-translator/config.json` and set `deepseek_api_key` or `openai_api_key`. Command-line options, environment variables, and this file take precedence over the Plasma widget configuration.

## Privacy

Single-word dictionary lookups are local. Text is sent to an online service only after you explicitly confirm a sentence translation or request online translation for a word. Online translations are cached locally, including the source text. API keys saved through the widget settings are stored in the Plasma user configuration and are not encrypted. See [PRIVACY.md](PRIVACY.md) for details.

## License

The widget is released under the [MIT License](LICENSE). Dictionary data comes from [ECDICT](https://github.com/skywind3000/ECDICT) under the MIT License; its license is included in the package.
