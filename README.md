# Selection Translator / 划词翻译

Selection Translator displays Chinese translations for English text selected on the desktop. It provides separate panel frontends for KDE Plasma 6 and GNOME Shell 46, backed by the same Python translation service.

Single words are looked up locally in the bundled ECDICT database. Sentence translation and optional online word translation support DeepSeek, OpenAI, and Google Translate, and are only triggered after explicit user action.

## Features

- Offline Chinese dictionary lookup for selected English words.
- Optional online translation for sentences and individual words.
- Configurable DeepSeek, OpenAI, and Google Translate priority.
- Optional clipboard monitoring.
- One backend and synchronized state across frontend instances.
- Compact panel result with a detailed popup view.

## Desktop Support

| Desktop | Session | Status | Selection backend |
| --- | --- | --- | --- |
| KDE Plasma 6 | Wayland | Supported | `wl-paste --watch` |
| KDE Plasma 6 | X11 | Supported on current `main` | `xclip` polling; `xsel` fallback for PRIMARY |
| GNOME Shell 46 | X11 | Tested on Ubuntu 24.04.3 | `xclip` polling |
| GNOME Shell 46 | Wayland | Best effort | `wl-paste`; compositor restrictions apply |

GNOME Wayland may prevent background access to another application's primary selection. Copying the text may work as a fallback, but global selection monitoring is not guaranteed.

## Other Desktop Environments

Not using Plasma or GNOME? Clone the repository and ask your coding agent to adapt the frontend to your desktop environment. The dictionary, translation providers, cache, state transitions, and D-Bus backend are already separated from the desktop UI, so a new port can usually reuse the existing core.

For example, give your coding agent the repository and a prompt like:

```text
Adapt Selection Translator to <desktop environment and version>.
Reuse the existing Python translation backend and shared state.
Add a native panel UI, an idempotent user installer, documentation, and tests.
Keep offline word lookup local and require explicit confirmation before sending text online.
Do not break the existing Plasma or GNOME frontends.
```

Ports to other desktops are welcome as pull requests.

## Requirements

Common requirements:

- Python 3
- Python D-Bus bindings
- PyGObject
- The ECDICT SQLite database

Session-specific requirements:

- Wayland: `wl-clipboard`
- X11: `xclip` (`xsel` can only act as a PRIMARY-selection fallback)

On Arch Linux, the common package names are `python-dbus`, `python-gobject`, and `wl-clipboard`. On Debian and Ubuntu they are usually `python3-dbus`, `python3-gi`, and `wl-clipboard`.

## KDE Plasma Installation

The `.plasmoid` release contains the Plasma frontend and the complete offline dictionary. Download it from the latest [GitHub Release](https://github.com/Noahwangyuchen/selection-translator/releases/latest), then run:

```sh
kpackagetool6 -t Plasma/Applet -i selection-translator-0.3.3.plasmoid
```

Use `-u` instead of `-i` to update an existing installation. Then add `Selection Translator` / `划词翻译` to a Plasma panel.

The GNOME frontend and X11 polling support were merged after `v0.3.3` and are currently available from `main`, not from the `v0.3.3` `.plasmoid` asset.

## GNOME Shell Installation

The GNOME frontend is currently installed from the source repository; it is not included in the `.plasmoid` file. GNOME Shell 46 is the supported extension version.

First clone the repository and build the dictionary:

```sh
git clone https://github.com/Noahwangyuchen/selection-translator.git
cd selection-translator
curl -L -o vendor/ecdict.csv https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv
python3 scripts/build_ecdict_sqlite.py vendor/ecdict.csv package/contents/data/ecdict.sqlite3
```

Install and enable the extension:

```sh
scripts/install_gnome.sh
gnome-extensions enable selection-translator@noahwangyuchen.local
```

The installer:

- installs the extension under `~/.local/share/gnome-shell/extensions/`;
- installs the backend and dictionary under `~/.local/share/selection-translator/`;
- creates and starts `~/.config/systemd/user/selection-translator.service`;
- creates `~/.config/selection-translator/config.json` only if it does not already exist.

A GNOME Shell restart or log out/in may be required after the first installation. Set `PYTHON_BIN` before running the installer if `dbus` and `gi` are provided by a non-default Python interpreter.

## Build Plasma From Source

After building the dictionary as shown above, install or update the Plasma package with:

```sh
kpackagetool6 -t Plasma/Applet -u package
```

## Configuration

On Plasma, right-click the widget and open `翻译服务`. The configuration page controls clipboard monitoring, API credentials, models, service URLs, and translation service priority.

On GNOME, edit:

```text
~/.config/selection-translator/config.json
```

Environment variables and `~/.config/selection-translator/config.json` take precedence over Plasma widget configuration. Supported environment variables include:

```sh
export DEEPSEEK_API_KEY='sk-...'
export DEEPSEEK_MODEL='deepseek-v4-flash'
export OPENAI_API_KEY='sk-...'
export OPENAI_MODEL='gpt-5-nano'
```

## How It Works

One session D-Bus service owns the selection listeners and shared translation state. On Wayland it uses `wl-paste --watch`; on X11 it polls through `xclip`, with `xsel` available as a PRIMARY-selection fallback. Plasma widgets receive D-Bus state signals, while the GNOME extension watches the same shared state file.

The service avoids duplicate online requests, rejects stale results, caches successful online translations, and synchronizes multiple frontend instances. Clipboard-triggered translation can be disabled; manual refresh remains available.

## Privacy

Single-word dictionary lookups are local. Selected text is sent to an online service only after you confirm sentence translation or request online translation for a word. Online translation caches contain source and translated text.

API keys saved through Plasma settings are stored in the per-user Plasma configuration and are not encrypted. The GNOME installer creates a new configuration file with user-only permissions. See [PRIVACY.md](PRIVACY.md) for details.

## Development

Run the backend and state tests with:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
QT_QPA_PLATFORM=offscreen qmltestrunner -input tests/tst_state_transitions.qml
QT_QPA_PLATFORM=offscreen qmltestrunner -input tests/tst_config_ui.qml
```

## License

The project is released under the [MIT License](LICENSE). Dictionary data comes from [ECDICT](https://github.com/skywind3000/ECDICT) under the MIT License; its license is included in the package.
