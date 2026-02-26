import { useState } from 'react';
import { postConfig } from '../api';
import type { SessionConfig } from '../types';
import GradingSchemeEditor from './GradingSchemeEditor';

interface Props {
  onConfigured: (cfg: SessionConfig) => void;
}

export default function SetupPage({ onConfigured }: Props) {
  const [examsDir, setExamsDir] = useState('');
  const [studentsCsv, setStudentsCsv] = useState('');
  const [gradingScheme, setGradingScheme] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showEditor, setShowEditor] = useState(false);

  const fillSampleData = () => {
    setExamsDir('/app/sample_data/exams');
    setStudentsCsv('/app/sample_data/students.csv');
    setGradingScheme('/app/sample_data/grading_scheme.json');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const cfg = await postConfig({
        exams_dir: examsDir,
        students_csv: studentsCsv,
        grading_scheme: gradingScheme,
      });
      onConfigured(cfg);
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : 'Failed to configure session';
      setError(msg ?? 'Failed to configure session');
    } finally {
      setLoading(false);
    }
  };

  if (showEditor) {
    return (
      <div className="setup-page setup-page--wide">
        <GradingSchemeEditor
          onSaved={(path) => {
            setGradingScheme(path);
            setShowEditor(false);
          }}
          onCancel={() => setShowEditor(false)}
        />
      </div>
    );
  }

  return (
    <div className="setup-page">
      <h1>Exam Grader Setup</h1>
      <div className="setup-sample-row">
        <button type="button" className="nav-btn" onClick={fillSampleData}>
          📂 Use Sample Data
        </button>
        <span className="setup-sample-hint">Auto-fills Docker paths for sample_data/</span>
      </div>
      <form onSubmit={handleSubmit} className="setup-form">
        <div className="form-group">
          <label htmlFor="exams-dir">Exams Directory (absolute path)</label>
          <input
            id="exams-dir"
            type="text"
            value={examsDir}
            onChange={(e) => setExamsDir(e.target.value)}
            placeholder="/app/sample_data/exams"
            required
          />
        </div>
        <div className="form-group">
          <label htmlFor="students-csv">Students CSV (absolute path)</label>
          <input
            id="students-csv"
            type="text"
            value={studentsCsv}
            onChange={(e) => setStudentsCsv(e.target.value)}
            placeholder="/app/sample_data/students.csv"
            required
          />
        </div>
        <div className="form-group">
          <label htmlFor="grading-scheme">Grading Scheme JSON (absolute path)</label>
          <div className="grading-scheme-input-row">
            <input
              id="grading-scheme"
              type="text"
              value={gradingScheme}
              onChange={(e) => setGradingScheme(e.target.value)}
              placeholder="/app/sample_data/grading_scheme.json"
              required
            />
            <button
              type="button"
              className="nav-btn"
              onClick={() => setShowEditor(true)}
              title="Open visual grading scheme editor"
            >
              Create / Edit
            </button>
          </div>
        </div>
        {error && <div className="error-message">{error}</div>}
        <button type="submit" disabled={loading} className="submit-btn">
          {loading ? 'Configuring...' : 'Start Grading'}
        </button>
      </form>
    </div>
  );
}
