# Privacy

Selection Translator monitors text exposed by the desktop selection system so it can perform local dictionary lookups.

## Local Processing

- Single English words are looked up in the bundled ECDICT database.
- Selection state is shared between widget instances through the session D-Bus.
- Clipboard monitoring can be disabled in the widget settings.
- Translation state and online translation cache files are stored under `~/.cache/selection-translator/`.

The cache can contain selected source text and translated text. Remove that directory to clear it.

## Network Requests

Selected text is not sent to an online translation service automatically. A network request occurs only when the user:

- confirms translation of a multi-word selection; or
- clicks the online translation action for a dictionary word.

The configured service order can include DeepSeek, OpenAI, and Google Translate. Their respective privacy policies apply to text sent to them. The Google Translate fallback uses a public web endpoint and may change or become unavailable without notice.

## Credentials

API keys entered in the widget configuration are stored in the per-user Plasma configuration file. They are not committed to this repository, sent to any service other than their configured API endpoint, or included in diagnostic output by the widget. They are not encrypted at rest, so the security of those keys relies on the permissions and security of the local user account.
