# Application Shortcut Catalog

Voice Keyboard Engine is integrating Office, WPS, and Feishu as Application Shortcut Catalog targets, not as product-specific plugins. The engine should keep acting like a lightweight voice-driven keyboard layer: it listens for spoken intent, resolves a named Shortcut Invocation from the current Input Environment, and sends the local keyboard-style action for that application.

Shortcut Invocation is intentionally not a power-user macro surface. The catalog should cover the common, low-conflict keyboard operations that remove repeated work for ordinary users. It should avoid exhaustive menu coverage, brittle surface guesses, and conflict-prone shortcuts that only serve edge-case workflows.

## Current Slice

- `agent/app_shortcut_presets.py` is the placeholder for built-in macOS Application Shortcut Catalog presets. It is intentionally empty in the current slice.
- `agent/typer.py` keeps the platform key parsing and key emission implementation.
- `agent/local_operation_catalog.py` owns local operation catalog entries, operation kind metadata, de-duplication, blocking, and high-risk policy decisions. The user-facing UI can still present these as `快捷键` or shortcut actions.
- `agent/app_launcher.py` owns application launch config parsing, macOS `.app` discovery, spoken launch aliases, and cross-platform launch execution.
- `agent/macos_window_actions.py` owns macOS window action dispatch by using Accessibility to inspect the frontmost window and write its frame.
- The engine should prefer a small Global Shortcut Catalog for universal editing actions before application-specific catalogs. Current universal actions include save, copy, cut, paste, undo, redo, select all, bold, italic, underline, and find.
- Application presets should not repeat universal editing actions with the same key sequence. They should contain only app-specific actions or app overrides where the same user-visible action needs a different key sequence.
- The current macOS built-in application shortcut presets are empty. Application-specific shortcuts for Office, WPS, Feishu/Lark, browsers, developer tools, and chat apps must be added through local config until there is a validated surface-aware adapter.
- Browsers, developer tools, generic chat apps, screenshot tools, and other productivity apps should not enter the built-in catalog by default. They can still be added locally through `typing.application_shortcuts` when a user wants to test them.
- Application launch is broader than application shortcuts. On macOS, the engine discovers installed `.app` bundles from `/Applications`, `~/Applications`, `/System/Applications`, and `/System/Applications/Utilities`, then exposes `打开<应用名>` actions for those local apps.
- `agent/app_launch_presets.py` keeps high-value spoken aliases such as `打开飞书`, `打开谷歌浏览器`, and `打开PPT` stable when the installed bundle name differs from what the user says.
- `打开设置` is intentionally not a built-in action because it is too easy for a provider to confuse with app-launch requests. Users should say `打开系统设置` for System Settings.
- macOS system window actions are built-in System Actions backed by Accessibility frame updates. The current small set is `窗口左半屏`, `窗口右半屏`, `窗口左移`, `窗口右移`, `窗口最大化`, and `窗口居中`. They calculate the target rectangle from the active screen visible frame, exit full-screen windows first, and then write `AXPosition`/`AXSize`.
- The product-facing customization entry is the menu bar app: Voice Keyboard -> `快捷键...`. The tab lists the current Shortcut Catalog, labels internal operation kinds such as key action, app launch, and window action, allows users to disable/restore named actions, and saves custom global actions under `typing.shortcuts`.
- Additional local application launch aliases belong in `typing.app_launches`. The Speech Interpretation Provider still must choose a discovered or configured action; it should not invent executable app names.
- WPS Office exposes multiple surfaces inside one application. Future WPS surface-specific actions should use prefixed names such as `WPS文字居中`, `WPS表格自动求和`, or `WPS演示新建幻灯片` instead of generic names like `居中` or `筛选`.
- Future WPS built-in actions should cover only common formatting, editing, and presentation operations. Exhaustive menu coverage stays out until there is a reliable surface detector and validation path.
- Feishu/Lark built-in application shortcuts are currently empty while the engine cannot reliably identify the active Feishu surface. Universal editing actions come from the Global Shortcut Catalog.
- Do not expose Feishu surface-specific actions such as search, find, filter, align, font size, or font color until the engine can tell whether the user is in chat, docs, sheets, Bitable, comments, or another Feishu surface.
- Do not use alias tables to guess Feishu surface-specific actions from speech such as "表格查找". If the exact surface is unknown, prefer not executing over executing the wrong shortcut.
- `typing.blocked_shortcuts` and `typing.blocked_shortcut_keys` let local config suppress actions or physical key sequences that are stolen by system or third-party global shortcuts.
- `AIHandler` already passes the current active application and available shortcut names into Instruction Mode classification.
- The Speech Interpretation Provider may choose only from the local Shortcut Catalog names it receives.

## Next Slices

1. Add a validated surface-aware adapter for application-specific Office, WPS, and Feishu/Lark shortcut presets.
2. Add Windows application identities and shortcut presets for the same validated slice.
3. Add a Feishu surface detector before reintroducing surface-specific Shortcut Invocation names.
4. Add Feishu Bitable runtime validation for menu-only formatting actions such as search, filter, font size, font color, and alignment variants.
5. Add a confirmation path for high-risk Shortcut Invocation such as send, submit, close, broad delete, and cross-application actions.
6. Add a small runtime diagnostic command that prints the current active application label and current Application Shortcut Catalog.

## Feishu OpenAPI Note

Feishu Bitable OpenAPI is a data-layer integration path for apps, tables, views, fields, records, and permissions. It is not a local shortcut discovery path for the current desktop Input Environment. Feishu Sheets has style APIs for cell formatting, but that is a cloud document mutation path and should stay separate from this local Shortcut Invocation slice unless the product explicitly chooses a cloud-document adapter.

## Product Rule

Do not move Office document semantics, WPS account behavior, Feishu workspace behavior, subscription flows, provider billing, or TypeUp product flows into this repository. This repository owns the local Voice Keyboard Operation and the keyboard-side adapters only.
