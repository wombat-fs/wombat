---
name: wombat-roadmap-state
description: Current build phase completion state for Wombat
metadata:
  type: project
---

Phases 0–8a complete (369 tests passing). Phase 8b (derivative pipeline) is next.

**Why:** Each phase builds on the previous; Phase 8a adds event YAML loading and multi-channel layer application.

**How to apply:** When starting new work, pick up from Phase 8b (port funscript-tools signal_ops, conversions, motion_axis, runner).

## Phase 8a deliverables (complete)
- `wombat/domain/events/` package: model.py (NormalizationConfig, Step, EventDefinition, EventLibrary), yaml_loader.py (parse event_definitions.yml incl. $var resolution), apply.py (translate_event → (channel_name, Layer) pairs; apply_modulation + apply_linear_change translators; op registry with warnings for unknown ops)
- `UndoStack.snapshot_multi_structural` — one undo entry across multiple channels
- `EditorController.apply_event_layers` — resolves channel names, snapshots, inserts, emits in one undo step
- `wombat/ui/events_panel.py` — load YAML, list events by group, configure start time + duration, Apply button; auto-loads repo YAML at startup; sync to playhead via `player.position_changed`
- Events panel wired into main_window as a tabbed dock (alongside Channels/Layers, Snippets)
- `WaveformSnippet` extended with `duty_cycle` parameter (square wave support)
- `tests/test_events.py` — 43 tests covering normalization rules, YAML loader, translate_event, EditorController integration, undo, and duty_cycle

## Phase 7 deliverables (complete)
- `wombat/domain/snippets/` package: base.py (ParamSpec, BeatSnippet, WaveformSnippet), rhythms.py (ConstantBeat, Subdivided, Swing, Euclidean, Accelerando), positions.py (Alternate, Constant, Ramp, Random, Sine/Triangle/Square/Sawtooth, AlternateOverBase, FollowBase), library.py (21 named presets + registry)
- `EditorController.insert_snippet_as_layer` and `fill_layer_with_snippet`
- `wombat/ui/snippet_panel.py` — tabbed dock with auto-param controls, live preview canvas, span picker, blend/fade options, insert button
- Snippet panel wired into main_window as a tabbed dock alongside Channels/Layers
- `tests/test_snippets.py` — 54 tests covering rhythms, positions, snippets, library, editor integration, domain isolation
