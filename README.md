<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/wombat-lockup-dark-800.png">
    <img src="assets/wombat-lockup-800.png" alt="Wombat" width="400">
  </picture>
</p>

# Wombat

**A cross-platform funscript authoring and editing tool.**

Wombat is a desktop editor for [funscripts](#the-funscript-format) — the JSON
files that drive haptic devices in sync with a video. It aims to be a viable,
actively-maintained alternative to [OpenFunscripter (OFS)](https://github.com/OpenFunscripter/OFS)
that runs on macOS, Linux, and Windows, with a non-destructive **layer** system
on top of every channel as its defining feature.

> **Status:** early but functional. The core editor — video playback, the
> multi-channel timeline, editing, layers, snippets, events, beat detection, and
> a Python plugin API — is built and covered by tests. Expect rough edges and
> changing internals.

Wombat is **not** an AI script generator. It's an editor: bring a draft (your
own, or the output of another tool) and refine it, or build one from scratch.

## Features

- **Multi-channel projects** — edit several funscripts (`orig`, `alpha`, `beta`,
  `volume`, `frequency`, pulse axes, …) against a single video.
- **Non-destructive layers** — stack action snippets that override lower levels,
  with configurable smooth fade-in/out transitions. Nothing is destroyed; you can
  re-edit or remove any layer.
- **Frame-accurate playback** via libmpv, with frame stepping and exact seeking —
  the whole reason libmpv was chosen over other players.
- **Snippet library** — drum-beat and waveform pattern generators (alternating,
  sinusoidal, Euclidean rhythms, ramps) for quickly laying down `pos` values.
- **Events** — load `event_definitions.yml` files and apply multi-channel events
  (modulation, fades, set-value) across axes at once.
- **Audio & beats** — a waveform underlay, beat detection, and snap-to-beat when
  placing and moving actions. Detection is optional and needs an external tool
  ([setup](docs/user/audio-and-beats.md#setting-up-beat-detection)).
- **Chapters, metadata, and export** — chapter markers, per-channel metadata,
  funscript export, and heatmap images.
- **Python plugin API** — extend Wombat with native Python plugins.
- **Keyboard-driven** — most commands have shortcuts, and keybindings are
  customisable.

## The funscript format

A funscript is a JSON file mapping device positions to timestamps:

```json
{
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

- `at` — time from the start, in milliseconds (int)
- `pos` — device position/intensity, 0–100 (int)
- `inverted` — optional; flips `pos` values
- `range` — optional; the position span (default 0–100)

## Installing

### Prerequisite: libmpv

Wombat plays video through `python-mpv`, a ctypes binding — **libmpv must be
installed on your system first.**

| Platform | Command |
|---|---|
| **macOS (Apple Silicon)** | `brew install mpv` (installs `libmpv.dylib` under `/opt/homebrew/lib`) |
| **Linux (Debian/Ubuntu)** | `sudo apt install libmpv2` (or `libmpv-dev`) |
| **Windows** | Download `libmpv-2.dll` and place it on the DLL search path (e.g. next to the executable) |

> **macOS troubleshooting:** if you hit an error loading libmpv, ctypes'
> `find_library('mpv')` sometimes can't locate the Homebrew dylib. Work around it
> with `export MPV_DYLIB_PATH=/opt/homebrew/lib/libmpv.dylib`.

macOS support targets **Apple Silicon** only; Linux and Windows target x86-64.

### Run

```bash
# Install uv if you don't have it: https://docs.astral.sh/uv/
uv sync --extra dev
uv run wombat

# Or without uv:
pip install -e ".[dev]"
python -m wombat
```

## Documentation

New here? Start with the **[User Guide](docs/user/README.md)** — the
[Quick Start](docs/user/quick-start.md) walks you from opening a video to
exporting a script, and the advanced pages cover layers, snippets, events, and
beats.

## Development

```bash
uv run pytest                  # tests
uv run ruff check .            # lint
uv run ruff format --check .   # format check
uv run mypy wombat             # type checking (advisory)
```

The architecture overview and phased build plan live in
[ROADMAP.md](ROADMAP.md); repo-wide conventions for contributors (and AI
assistants) are in [CLAUDE.md](CLAUDE.md).

## Contributing

Issues and pull requests are welcome. If you're planning a larger change, please
open an issue first so we can talk through the approach.

## Acknowledgements

Wombat's default event library is
[funscript-tools](https://github.com/edger477/funscript-tools)'
`config.event_definitions.yml` by **edger477**, bundled under the MIT License
(Copyright © 2024 edger477); the license travels with the file in
[wombat/resources/](wombat/resources/). Wombat also takes UX inspiration from
[OpenFunscripter](https://github.com/OpenFunscripter/OFS).

## License & donations

Wombat is released under the [MIT License](LICENSE) — free to use, including
commercially. If Wombat is useful to you in a commercial setting, a donation to
support ongoing maintenance is appreciated but never required.
