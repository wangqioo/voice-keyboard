# Repository Boundaries

`voice-keyboard` is the standalone local engine. It should stay useful without the TypeUp desktop app or TypeUp backend.

## This Repository: Voice Keyboard Engine

Owns:

- Microphone capture and device enumeration.
- Push-to-talk and VAD recording modes.
- Global keyboard and mouse monitoring.
- Text input, erase, clipboard, and shortcut behavior across platforms.
- STT provider adapters.
- LLM editing provider adapters.
- macOS, Windows, and Linux permissions, autostart, and native helper UI.
- Engine packaging that is independent of a specific cloud product.

Should not own:

- TypeUp account UI.
- Subscription purchase flows.
- Payment provider business logic.
- Cloud entitlement policy.
- Electron local bridge implementation.

## TypeUp Desktop: `oxygen0827/typeup-win`

TypeUp Desktop embeds this engine for product packaging and adds:

- Electron and React UI.
- A local Node bridge.
- Account/session synchronization.
- Desktop packaging for Windows and macOS.

Generic engine fixes made in the TypeUp embedded copy should be upstreamed here. Product-specific integration can remain in TypeUp Desktop if it is only about packaging, local bridge state, or UI status.

## TypeUp Backend: `oxygen0827/typeup-backend`

The backend owns cloud concerns:

- Users, sessions, and refresh token rotation.
- Plans, orders, payments, and entitlement state.
- Usage metering and quota enforcement.
- STT/LLM model proxy APIs and provider credentials.

The engine may include a `typeup_backend` provider as one provider adapter, but the engine should not contain backend payment or account business logic.

## Sync Policy

- Prefer implementing generic engine behavior in this repository first.
- If a fix lands first in TypeUp Desktop's embedded engine, create a follow-up PR here.
- Keep TypeUp-specific behavior isolated behind provider names or integration modules.
- Avoid manual copy-paste sync without a commit message explaining the source and target revisions.
