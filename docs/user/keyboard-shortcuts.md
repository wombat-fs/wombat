# Keyboard Shortcuts

Defaults are listed below. Anything marked *(unbound)* works from its menu but has
no default key — assign one if you use it often (see
[Customising](#customising-shortcuts)).

## Playback

| Action | Default |
|---|---|
| Play / pause | `Space` |
| Step one frame forward / back | `→` / `←` |
| Seek 5 s forward / back | `Ctrl+→` / `Ctrl+←` |
| Previous / next chapter | `[` / `]` |

> When the **timeline** has keyboard focus, plain `←` / `→` instead jump between
> adjacent actions; frame-stepping then happens from the video/transport focus.

## File & project

| Action | Default |
|---|---|
| New project | `Ctrl+N` |
| Open project | `Ctrl+O` |
| Open media | `Ctrl+Shift+O` |
| Save project | `Ctrl+S` |
| Save project as | `Ctrl+Shift+S` |
| Export funscripts | *(unbound)* |
| Quit | `Ctrl+Q` |

## Editing

| Action | Default |
|---|---|
| Undo / Redo | `Ctrl+Z` / `Ctrl+Y` |
| Cut / Copy / Paste | `Ctrl+X` / `Ctrl+C` / `Ctrl+V` |
| Paste exact (original times) | `Ctrl+Shift+V` |
| Delete selection | `Delete` / `Backspace` |
| Drop a point at pos 50 (playhead) | `P` |
| Nudge selection position ±1 | `↑` / `↓` |
| Nudge selection timing ½ frame | `Shift+←` / `Shift+→` |
| Invert / Equalize / Simplify | *(unbound — Edit ▸ Transform)* |

## Selection

| Action | Default |
|---|---|
| Select all | `Ctrl+A` |
| Select left / right of playhead | `Ctrl+Alt+←` / `Ctrl+Alt+→` |
| Set selection start / end | *(unbound)* |
| Isolate action | *(unbound)* |
| Top / Middle / Bottom points only | *(unbound)* |

## Position keys

Press to add an action at the playhead (or set the position of the current
selection). Ignored while a text field has focus.

| Key | Pos | Key | Pos | Key | Pos |
|---|---|---|---|---|---|
| `` ` `` | 0 | `4` | 40 | `8` | 80 |
| `1` | 10 | `5` | 50 | `9` | 90 |
| `2` | 20 | `6` | 60 | `0` | 100 |
| `3` | 30 | `7` | 70 | | |

## Customising shortcuts

Shortcuts live in a **`keybindings.json`** file. The quickest way in:

**Edit ▸ Preferences… ▸ Keybindings** shows the file's location and an option to
open it (creating a commented template the first time).

- Each entry maps an action name to a Qt key string (`"save": "Ctrl+S"`,
  `"select_top": "Ctrl+T"`, …).
- The **position keys** are configurable too — adjust the `` ` ``/`1`–`0` mapping
  to suit your keyboard layout.
- Missing keys fall back to the built-in defaults, and unknown keys are ignored,
  so you only need to list what you want to change.

Restart Wombat (or reopen the project) after editing the file for changes to take
effect.
