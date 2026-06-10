"""Tests for UndoStack — snapshot transactions, multi-target entries."""
from wombat.app.undo import UndoStack
from wombat.domain.action import Action, ActionList
from wombat.domain.channel import Channel, Layer


def _channel(name: str = "c", *pairs) -> Channel:
    al = ActionList(Action(t, p) for t, p in pairs)
    return Channel(name=name, layers=[Layer(actions=al)])


def _al(*pairs) -> ActionList:
    return ActionList(Action(t, p) for t, p in pairs)


# ------------------------------------------------------------------ basic snapshot/restore

def test_snapshot_then_undo_restores():
    ch = _channel("c", (0.0, 0), (1.0, 100))
    stack = UndoStack()
    stack.snapshot("add", [(ch, 0)], frozenset())
    ch.layers[0].actions.add(Action(2.0, 50))
    assert len(ch.layers[0].actions) == 3

    entry = stack.undo()
    assert entry is not None
    assert len(ch.layers[0].actions) == 2


def test_undo_returns_description():
    ch = _channel("c", (0.0, 0))
    stack = UndoStack()
    stack.snapshot("my edit", [(ch, 0)], frozenset())
    ch.layers[0].actions.add(Action(1.0, 50))
    entry = stack.undo()
    assert entry is not None
    assert entry.description == "my edit"


def test_undo_when_empty_returns_none():
    stack = UndoStack()
    assert stack.undo() is None


def test_can_undo_false_when_empty():
    stack = UndoStack()
    assert not stack.can_undo


def test_can_undo_true_after_snapshot():
    ch = _channel("c")
    stack = UndoStack()
    stack.snapshot("x", [(ch, 0)], frozenset())
    assert stack.can_undo


# ------------------------------------------------------------------ redo

def test_undo_then_redo_restores_post_edit_state():
    ch = _channel("c", (0.0, 0))
    stack = UndoStack()
    stack.snapshot("add", [(ch, 0)], frozenset())
    ch.layers[0].actions.add(Action(1.0, 100))

    stack.undo()
    assert len(ch.layers[0].actions) == 1  # back to pre-edit

    stack.redo()
    assert len(ch.layers[0].actions) == 2  # re-applied


def test_redo_when_empty_returns_none():
    stack = UndoStack()
    assert stack.redo() is None


def test_can_redo_false_initially():
    stack = UndoStack()
    assert not stack.can_redo


def test_can_redo_true_after_undo():
    ch = _channel("c", (0.0, 0))
    stack = UndoStack()
    stack.snapshot("x", [(ch, 0)], frozenset())
    ch.layers[0].actions.add(Action(1.0, 50))
    stack.undo()
    assert stack.can_redo


def test_new_edit_after_undo_clears_redo():
    ch = _channel("c", (0.0, 0))
    stack = UndoStack()
    stack.snapshot("first", [(ch, 0)], frozenset())
    ch.layers[0].actions.add(Action(1.0, 50))
    stack.undo()
    assert stack.can_redo

    stack.snapshot("second", [(ch, 0)], frozenset())
    assert not stack.can_redo


# ------------------------------------------------------------------ gesture (begin/commit/cancel)

def test_begin_commit_is_one_undo_step():
    ch = _channel("c", (0.0, 0))
    stack = UndoStack()
    stack.begin("drag", [(ch, 0)], frozenset())
    ch.layers[0].actions.add(Action(1.0, 50))
    ch.layers[0].actions.add(Action(2.0, 100))
    stack.commit()

    assert stack.can_undo
    stack.undo()
    assert len(ch.layers[0].actions) == 1  # back to original single action


def test_cancel_restores_state():
    ch = _channel("c", (0.0, 0))
    stack = UndoStack()
    stack.begin("drag", [(ch, 0)], frozenset())
    ch.layers[0].actions.add(Action(1.0, 50))
    stack.cancel()
    assert len(ch.layers[0].actions) == 1
    assert not stack.can_undo


def test_cancel_leaves_redo_empty():
    ch = _channel("c", (0.0, 0))
    stack = UndoStack()
    stack.begin("drag", [(ch, 0)], frozenset())
    ch.layers[0].actions.add(Action(1.0, 50))
    stack.cancel()
    assert not stack.can_redo


# ------------------------------------------------------------------ selection round-trip

def test_undo_restores_selection():
    ch = _channel("c", (0.0, 0), (1.0, 100))
    stack = UndoStack()
    sel_before = frozenset({0.0})
    stack.snapshot("edit", [(ch, 0)], sel_before)
    ch.layers[0].actions.add(Action(2.0, 50))

    entry = stack.undo(current_selection=frozenset({1.0}))
    assert entry is not None
    assert entry.snapshots[0].selection == sel_before


# ------------------------------------------------------------------ multi-target

def test_multi_target_undo_restores_all():
    ch1 = _channel("a", (0.0, 0))
    ch2 = _channel("b", (0.0, 50))
    stack = UndoStack()
    stack.snapshot("multi", [(ch1, 0), (ch2, 0)], frozenset())

    ch1.layers[0].actions.add(Action(1.0, 100))
    ch2.layers[0].actions.add(Action(1.0, 75))

    stack.undo()
    assert len(ch1.layers[0].actions) == 1
    assert len(ch2.layers[0].actions) == 1


# ------------------------------------------------------------------ cache invalidation

def test_undo_invalidates_synthesis_cache():
    ch = _channel("c", (0.0, 0))
    _ = ch.synthesize()  # warm cache
    assert ch._synthesis_cache  # warm (non-empty)

    stack = UndoStack()
    stack.snapshot("add", [(ch, 0)], frozenset())
    ch.layers[0].actions.add(Action(1.0, 100))
    stack.undo()
    assert not ch._synthesis_cache  # invalidated (empty dict)


# ------------------------------------------------------------------ descriptions

def test_descriptions_lists():
    ch = _channel("c")
    stack = UndoStack()
    stack.snapshot("first", [(ch, 0)], frozenset())
    stack.snapshot("second", [(ch, 0)], frozenset())
    ch.layers[0].actions.add(Action(1.0, 50))
    stack.undo()

    undo_d, redo_d = stack.descriptions()
    assert "first" in undo_d
    assert "second" in redo_d
