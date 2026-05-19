# macOS window actions use Accessibility frames

## Status

Accepted.

## Context

Voice Keyboard Operation names such as `窗口左半屏`, `窗口右半屏`, `窗口最大化`, and `窗口居中` are System Actions in the local Shortcut Catalog. A previous implementation dispatched configured macOS window-management shortcuts for these actions, but that made the action depend on the user's current system shortcut configuration or external window manager. In practice, Instruction Mode could resolve the right operation while the active window did not move.

The earlier Accessibility implementation moved the frontmost window directly by reading `AXFocusedWindow` or falling back to `AXWindows[0]`, calculating a target rectangle from the active screen visible frame, and writing `AXPosition` plus `AXSize`.

## Decision

macOS window actions execute through Accessibility frame updates, not configured keyboard shortcuts.

The engine:

- Finds the current application PID from the active Input Environment.
- Reads the frontmost window through `AXFocusedWindow`, falling back to the first `AXWindows` entry.
- Reads `AXPosition` and `AXSize`.
- Converts `NSScreen.visibleFrame()` into AX coordinates using the screen whose frame origin is `(0, 0)` as the stable reference, not dynamic `NSScreen.mainScreen()`.
- Selects the visible screen containing the window center.
- Calculates the target rectangle for left half, right half, maximize, or center.
- Exits full-screen windows by setting `AXFullScreen` to false before applying a frame.
- Applies the frame through ordered `AXPosition` and `AXSize` updates.

The write order is intentional:

- Windows larger than the target should shrink before moving, so macOS does not constrain the still-large window into an inaccessible position.
- Windows smaller than the target move to the target origin, expand, and then realign. This avoids expanding from an off-target edge where the application or macOS may clamp the result.
- Some applications constrain final height or y position. The engine treats a frame as successful when it satisfies the requested half-screen edge and width, even if the application clamps vertical pixels.

## Consequences

Window movement now requires macOS Accessibility permission for the running app identity.

The Shortcut Catalog still exposes these as named System Actions so the Speech Interpretation Provider can choose a bounded operation name. The execution path is not a configurable shortcut surface.
