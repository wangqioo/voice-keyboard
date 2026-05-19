# Application Shortcut Catalog

Voice Keyboard Engine is integrating Office, WPS, and Feishu as Application Shortcut Catalog targets, not as product-specific plugins. The engine should keep acting like a lightweight voice-driven keyboard layer: it listens for spoken intent, resolves a named Shortcut Invocation from the current Input Environment, and sends the local key sequence for that application.

## Current Slice

- `agent/app_shortcut_presets.py` owns built-in macOS Application Shortcut Catalog presets.
- `agent/typer.py` keeps the platform key parsing and key emission implementation.
- The current macOS presets include Microsoft Word, Microsoft Excel, Microsoft PowerPoint, WPS Office, and Feishu/Lark.
- The Feishu/Lark presets include an initial Feishu Bitable action set for common editing Shortcut Invocation names.
- Unverified or high-conflict Feishu Bitable formatting actions such as alignment, font size, and font color should not be added as executable shortcuts until they are validated in the app. For example, public Feishu shortcut material shows `Command + Shift + E` can mean refresh view in another Feishu surface, so it must not be guessed as center alignment.
- `typing.blocked_shortcuts` and `typing.blocked_shortcut_keys` let local config suppress actions or physical key sequences that are stolen by system or third-party global shortcuts.
- `AIHandler` already passes the current active application and available shortcut names into Instruction Mode classification.
- The Speech Interpretation Provider may choose only from the local Shortcut Catalog names it receives.

## Next Slices

1. Move Shortcut Catalog composition, aliases, and risk metadata out of `agent/typer.py` into a deeper catalog module.
2. Add Windows application identities and shortcut presets for Word, Excel, PowerPoint, WPS, and Feishu.
3. Add application-aware action aliases, such as mapping "加粗一下", "设成标题一", "开筛选", or "多维表格居中一下" to canonical catalog names.
4. Add Feishu Bitable runtime validation for menu-only formatting actions such as font size, font color, and alignment variants.
5. Add a confirmation path for high-risk Shortcut Invocation such as send, submit, close, broad delete, and cross-application actions.
6. Add a small runtime diagnostic command that prints the current active application label and current Application Shortcut Catalog.

## Feishu OpenAPI Note

Feishu Bitable OpenAPI is a data-layer integration path for apps, tables, views, fields, records, and permissions. It is not a local shortcut discovery path for the current desktop Input Environment. Feishu Sheets has style APIs for cell formatting, but that is a cloud document mutation path and should stay separate from this local Shortcut Invocation slice unless the product explicitly chooses a cloud-document adapter.

## Product Rule

Do not move Office document semantics, WPS account behavior, Feishu workspace behavior, subscription flows, provider billing, or TypeUp product flows into this repository. This repository owns the local Voice Keyboard Operation and the keyboard-side adapters only.
