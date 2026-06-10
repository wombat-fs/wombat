Wombat (tentative name) - Open source cross-platform funscript authoring and editing tool

# Development Setup

## Prerequisites: libmpv

`python-mpv` is a ctypes binding — **libmpv must be installed on your system** before running Wombat.

| Platform | Command |
|---|---|
| **macOS (Apple Silicon)** | `brew install mpv` — installs `libmpv.dylib` under `/opt/homebrew/lib` |
| **Linux (Debian/Ubuntu)** | `sudo apt install libmpv2` (or `libmpv-dev`) |
| **Windows** | Download `libmpv-2.dll` and place it on the DLL search path (e.g. next to the executable) |

> **Troubleshooting (macOS):** If you get an error loading libmpv, ctypes' `find_library('mpv')` sometimes fails to locate the Homebrew dylib. Set the environment variable `MPV_DYLIB_PATH=/opt/homebrew/lib/libmpv.dylib` as a workaround.

## Install and run

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (including dev extras)
uv sync --extra dev

# Launch the app
uv run wombat

# Alternatively, without uv:
pip install -e ".[dev]"
python -m wombat
```

## Development

```bash
# Run tests
uv run pytest

# Lint and format check
uv run ruff check .
uv run ruff format --check .

# Auto-fix formatting
uv run ruff format .

# Type checking (advisory)
uv run mypy wombat
```

# What is a funcscript?

Funscript is a JSON-based file format used to synchronize interactive devices
for haptic feedback with video playback. It operates on a simple timeline by
mapping physical device positions to specific timestamps in the video.

## Core JSON Structure

The format uses a few root properties and an array of objects known as
actions.

* version: Script version (usually "1.0")
* *inverted: Optional boolean that inverts device positions (100 becomes 0)
* range: Optional integer (default 0–100) defining the haptic position/intensity span
* actions: The core array mapping positions over time.

## Action Object Properties

Inside the actions array, each movement is defined by two mandatory properties:

* at: The time elapsed from the start of the script/video, measured in milliseconds (int)
* pos: The target position/intensity of the device on a scale from 0 to 100% (int)

### Example

```
json{
  "version": "1.0",
  "inverted": false,
  "range": 90,
  "actions": [
    { "pos": 0, "at": 100 },
    { "pos": 100, "at": 500 },
    { "pos": 20, "at": 800 }
  ]
}
```

# Other availble tools

While the underlying funscript is very simple, there is a need for a user
friendly authoring/editing tool that can run on all major platforms.

The most used tools has probably been OpenFunscripter (OFS), available at
https://github.com/OpenFunscripter/OFS, but this is Windows only and no longer
actively maintained. The aim is to make Wombat a viable alternative, but not a
direct clone of this. A copy of the OFS repo is available in the OFS folder for
reference.

There are other tools, most notably
https://github.com/ack00gar/FunGen-AI-Powered-Funscript-Generator that uses AI
models to automatically create a funscript from a video. This is useful and can
be the starting point for creating a preliminary version of a script that can be
input into Wombat for refining and editing. AI generation is out of scope for
Wombat.

# Technical stack (tentative)

* Python 3
* python-mpv (libmpv) for video playback, chosen for frame-accurate seeking/stepping and cross-platform support (documentation at https://github.com/jaseg/python-mpv)
* PySide6 for the UI (Python Qt wrappers)

# Capabilities

Wombat should be able to edit/create several funscripts connected to the same
video source, each called a *channel'. Typical channel names: 'orig', 'alpha', 'beta', 'volume', 'frequence', 'pulse-width', 'pulse-rise'.

I want each channel to be editable in a manner that resembles typical video
editing software: For each channel, we should have a base funscript actions
at/pos key value pair and it should be possible to add layers to this where a
layer can contain action snippets that override the data in lower levels.

Wombat synthesizes the layer stack with (definable smooth transitions when a new
layer fades in or out).

We should offer a number of base snippets creating drum-beat patters for the
'at' keys and give several algorithms for the corrsponding "pos" values. Simple
examples: pos alternating between two values, or slightly more complex, pos
alternating between two values added to base signal (sinusoid or similar), but
there are lot of other interesting patterns that we should offer in form of a
"snippet library"

There is a github repo https://github.com/edger477/funscript-tools, available in
the funscript-tools folder,  that builds a number of funscripts from a base one.
We should offer that functionality too, either by calling this program
externally or incorporating the algorithm directly. That tool also has an
interesting idea of "events" that affect several parallel funscript channels. I
want Wombat to offer a similar functionality, preferably allowing the yaml-files
from that repo to be used directly in Wombat.


# GUI

Similar to OFS.

Main widget shows a video source.

Underneath the channels are visible, drawn as affine graphs with a node at each
action in the funscript, and a clear visual representation of each layer,
similar to how it's done in video editing software.

Most commands should be accessible though keyboard shortcuts.
