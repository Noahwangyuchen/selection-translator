# Selection Translator 0.3.3

First public release.

## Highlights

- Offline Chinese dictionary lookup for selected English words.
- Manual sentence translation through DeepSeek, OpenAI, or Google Translate.
- Configurable online service priority and clipboard monitoring.
- Optional online translation for individual dictionary words.
- Shared D-Bus listener and synchronized state across multiple widget instances.
- Compact panel UI with sentence confirmation and selection-change debounce.

## Requirements

- KDE Plasma 6
- Python 3, Python D-Bus bindings, and PyGObject
- `wl-clipboard` on Wayland, or `xclip`/`xsel` on X11

Single-word lookups remain offline. See `PRIVACY.md` before configuring an online translation service.
