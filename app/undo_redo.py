"""Undo/redo manager for annotations and grades.

Every edit to annotations or grades is wrapped in an Action and pushed onto
an undo stack (max 100 entries).  The full stack is persisted to
``journal.json`` so history survives quit/relaunch.

Annotation actions store a single annotation's old and new state:
  * old_annotation is None  →  an annotation was **added**
  * new_annotation is None  →  an annotation was **deleted**
  * both non-None           →  an annotation was **modified**
"""

import json
import os
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional

from models import Annotation

MAX_HISTORY = 100


@dataclass
class Action:
    """A single undoable/redoable operation."""
    id: str
    action_type: str          # "annotation" or "grade"
    student_number: str
    # -- annotation fields (single annotation) --
    annotation_id: Optional[str] = None     # id of the affected annotation
    old_annotation: Optional[dict] = None   # None ⇒ annotation was added
    new_annotation: Optional[dict] = None   # None ⇒ annotation was deleted
    # -- grade fields --
    grade_key: Optional[str] = None
    old_grade: Optional[float] = None       # None ⇒ was unset
    new_grade: Optional[float] = None       # None ⇒ cleared


def snapshot_annotations(annotations: List[Annotation]) -> Dict[str, dict]:
    """Build an ``{id: dict}`` snapshot for the current annotation list."""
    return {ann.id: ann.to_dict() for ann in annotations}


def diff_snapshots(
    old: Dict[str, dict],
    new: Dict[str, dict],
) -> Optional[tuple]:
    """Compare two snapshots and return the single change, or *None*.

    Returns ``(annotation_id, old_dict_or_None, new_dict_or_None)``.
    """
    old_ids = set(old)
    new_ids = set(new)
    added = new_ids - old_ids
    if added:
        aid = added.pop()
        return (aid, None, new[aid])
    removed = old_ids - new_ids
    if removed:
        aid = removed.pop()
        return (aid, old[aid], None)
    for aid in old_ids & new_ids:
        if old[aid] != new[aid]:
            return (aid, old[aid], new[aid])
    return None


# ── Action serialisation ──────────────────────────────────────────────────────

def _action_to_dict(action: Action) -> dict:
    d: dict = {
        "id": action.id,
        "action_type": action.action_type,
        "student_number": action.student_number,
    }
    if action.action_type == "annotation":
        d["annotation_id"] = action.annotation_id
        d["old_annotation"] = action.old_annotation
        d["new_annotation"] = action.new_annotation
    elif action.action_type == "grade":
        d["grade_key"] = action.grade_key
        d["old_grade"] = action.old_grade
        d["new_grade"] = action.new_grade
    return d


def _dict_to_action(d: dict) -> Action:
    return Action(
        id=d["id"],
        action_type=d["action_type"],
        student_number=d["student_number"],
        annotation_id=d.get("annotation_id"),
        old_annotation=d.get("old_annotation"),
        new_annotation=d.get("new_annotation"),
        grade_key=d.get("grade_key"),
        old_grade=d.get("old_grade"),
        new_grade=d.get("new_grade"),
    )


# ── Manager ──────────────────────────────────────────────────────────────────

class UndoRedoManager:
    """Maintains undo/redo stacks and persists them to *journal.json*."""

    def __init__(self) -> None:
        self._undo_stack: List[Action] = []
        self._redo_stack: List[Action] = []
        self._journal_path: Optional[str] = None

    # -- Configuration --

    def set_journal_path(self, path: str) -> None:
        self._journal_path = path
        self._load_journal()

    # -- Stack operations --

    def push(self, action: Action) -> None:
        """Record a new action (clears the redo stack)."""
        self._undo_stack.append(action)
        self._redo_stack.clear()
        if len(self._undo_stack) > MAX_HISTORY:
            self._undo_stack = self._undo_stack[-MAX_HISTORY:]
        self._save_journal()

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def undo(self) -> Optional[Action]:
        if not self._undo_stack:
            return None
        action = self._undo_stack.pop()
        self._redo_stack.append(action)
        self._save_journal()
        return action

    def redo(self) -> Optional[Action]:
        if not self._redo_stack:
            return None
        action = self._redo_stack.pop()
        self._undo_stack.append(action)
        self._save_journal()
        return action

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._save_journal()

    # -- Persistence --

    def _save_journal(self) -> None:
        if not self._journal_path:
            return
        data = {
            "undo": [_action_to_dict(a) for a in self._undo_stack],
            "redo": [_action_to_dict(a) for a in self._redo_stack],
        }
        dir_name = os.path.dirname(self._journal_path)
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self._journal_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_journal(self) -> None:
        if not self._journal_path or not os.path.exists(self._journal_path):
            return
        try:
            with open(self._journal_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._undo_stack = [_dict_to_action(d) for d in data.get("undo", [])]
            self._redo_stack = [_dict_to_action(d) for d in data.get("redo", [])]
        except (json.JSONDecodeError, KeyError, TypeError):
            self._undo_stack.clear()
            self._redo_stack.clear()
