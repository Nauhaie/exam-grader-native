import { useState } from 'react';
import { postGradingScheme, getSampleGradingScheme } from '../api';
import type { GradingScheme, Exercise, Subquestion } from '../types';

interface Props {
  onSaved: (schemePath: string) => void;
  onCancel: () => void;
}

const SAVED_SCHEME_PATH = './data/grading_scheme.json';

function emptySubquestion(): Subquestion {
  return { name: '', max_points: 1 };
}

function emptyExercise(): Exercise {
  return { name: '', subquestions: [emptySubquestion()] };
}

export default function GradingSchemeEditor({ onSaved, onCancel }: Props) {
  const [exercises, setExercises] = useState<Exercise[]>([emptyExercise()]);
  const [saving, setSaving] = useState(false);
  const [loadingSample, setLoadingSample] = useState(false);
  const [successMsg, setSuccessMsg] = useState('');
  const [errorMsg, setErrorMsg] = useState('');

  const totalPoints = exercises.reduce(
    (sum, ex) => sum + ex.subquestions.reduce((s, sq) => s + (sq.max_points || 0), 0),
    0,
  );

  function updateExerciseName(exIdx: number, name: string) {
    setExercises((prev) =>
      prev.map((ex, i) => (i === exIdx ? { ...ex, name } : ex)),
    );
  }

  function removeExercise(exIdx: number) {
    setExercises((prev) => prev.filter((_, i) => i !== exIdx));
  }

  function addExercise() {
    setExercises((prev) => [...prev, emptyExercise()]);
  }

  function updateSubquestion(exIdx: number, sqIdx: number, field: keyof Subquestion, value: string | number) {
    setExercises((prev) =>
      prev.map((ex, i) =>
        i === exIdx
          ? {
              ...ex,
              subquestions: ex.subquestions.map((sq, j) =>
                j === sqIdx ? { ...sq, [field]: value } : sq,
              ),
            }
          : ex,
      ),
    );
  }

  function addSubquestion(exIdx: number) {
    setExercises((prev) =>
      prev.map((ex, i) =>
        i === exIdx ? { ...ex, subquestions: [...ex.subquestions, emptySubquestion()] } : ex,
      ),
    );
  }

  function removeSubquestion(exIdx: number, sqIdx: number) {
    setExercises((prev) =>
      prev.map((ex, i) =>
        i === exIdx
          ? { ...ex, subquestions: ex.subquestions.filter((_, j) => j !== sqIdx) }
          : ex,
      ),
    );
  }

  function validate(): string | null {
    if (exercises.length === 0) return 'At least one exercise is required.';
    for (let i = 0; i < exercises.length; i++) {
      if (!exercises[i].name.trim()) return `Exercise ${i + 1} name must not be empty.`;
      if (exercises[i].subquestions.length === 0)
        return `Exercise "${exercises[i].name}" must have at least one subquestion.`;
      for (let j = 0; j < exercises[i].subquestions.length; j++) {
        const sq = exercises[i].subquestions[j];
        if (!sq.name.trim())
          return `Subquestion ${j + 1} in exercise "${exercises[i].name}" must have a name.`;
        if (sq.max_points < 0.5)
          return `Subquestion "${sq.name}" in exercise "${exercises[i].name}" must have max points ≥ 0.5.`;
      }
    }
    return null;
  }

  async function handleLoadSample() {
    setLoadingSample(true);
    setErrorMsg('');
    setSuccessMsg('');
    try {
      const sample = await getSampleGradingScheme();
      setExercises(sample.exercises);
    } catch {
      setErrorMsg('Failed to load sample scheme.');
    } finally {
      setLoadingSample(false);
    }
  }

  async function handleSave() {
    setErrorMsg('');
    setSuccessMsg('');
    const validationError = validate();
    if (validationError) {
      setErrorMsg(validationError);
      return;
    }
    setSaving(true);
    try {
      const scheme: GradingScheme = { exercises };
      await postGradingScheme(scheme);
      setSuccessMsg('Scheme saved successfully.');
      onSaved(SAVED_SCHEME_PATH);
    } catch {
      setErrorMsg('Failed to save grading scheme.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="scheme-editor">
      <div className="scheme-editor-header">
        <h2>Grading Scheme Editor</h2>
        <div className="scheme-editor-header-actions">
          <span className="scheme-total-points">Total: {totalPoints} pts</span>
          <button
            type="button"
            className="nav-btn"
            onClick={handleLoadSample}
            disabled={loadingSample}
          >
            {loadingSample ? 'Loading…' : 'Load Sample'}
          </button>
        </div>
      </div>

      <div className="scheme-exercises">
        {exercises.map((ex, exIdx) => (
          <div key={exIdx} className="exercise-card">
            <div className="exercise-card-header">
              <input
                type="text"
                className="exercise-name-input"
                value={ex.name}
                onChange={(e) => updateExerciseName(exIdx, e.target.value)}
                placeholder={`Exercise ${exIdx + 1} name`}
              />
              <button
                type="button"
                className="danger-btn"
                onClick={() => removeExercise(exIdx)}
                disabled={exercises.length === 1}
                title="Remove exercise"
              >
                Remove Exercise
              </button>
            </div>

            <div className="subquestions-list">
              {ex.subquestions.map((sq, sqIdx) => (
                <div key={sqIdx} className="subquestion-row">
                  <input
                    type="text"
                    className="subquestion-name-input"
                    value={sq.name}
                    onChange={(e) => updateSubquestion(exIdx, sqIdx, 'name', e.target.value)}
                    placeholder="Name (e.g. 1a)"
                  />
                  <label className="subquestion-pts-label">pts</label>
                  <input
                    type="number"
                    className="subquestion-pts-input"
                    value={sq.max_points}
                    min={0.5}
                    step={0.5}
                    onChange={(e) =>
                      updateSubquestion(exIdx, sqIdx, 'max_points', parseFloat(e.target.value) || 0)
                    }
                  />
                  <button
                    type="button"
                    className="danger-btn danger-btn--small"
                    onClick={() => removeSubquestion(exIdx, sqIdx)}
                    disabled={ex.subquestions.length === 1}
                    title="Remove subquestion"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>

            <button
              type="button"
              className="nav-btn nav-btn--small"
              onClick={() => addSubquestion(exIdx)}
            >
              + Add Subquestion
            </button>
          </div>
        ))}
      </div>

      <button type="button" className="nav-btn scheme-add-exercise-btn" onClick={addExercise}>
        + Add Exercise
      </button>

      {errorMsg && <div className="error-message">{errorMsg}</div>}
      {successMsg && <div className="success-message">{successMsg}</div>}

      <div className="scheme-editor-footer">
        <button type="button" className="submit-btn" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save Scheme'}
        </button>
        <button type="button" className="nav-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
