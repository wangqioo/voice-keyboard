# Local shortcut catalog

Shortcut Invocation should target a named action from a local Shortcut Catalog. A Speech Interpretation Provider may choose among named shortcut actions that the engine provides in context, but it must not invent shortcut actions, key sequences, or app-specific macros.

The catalog may be composed from a Global Shortcut Catalog and an Application Shortcut Catalog. Global actions cover common system or broadly reusable shortcuts. Application actions cover the current application context and take precedence when names conflict.

The local engine keeps shortcut metadata, including source and risk signals. This keeps Shortcut Invocation aligned with voice-driven keyboard efficiency instead of provider-generated automation.
