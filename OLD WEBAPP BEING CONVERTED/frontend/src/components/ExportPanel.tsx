import { useState } from 'react';
import { exportGradesCSV, exportGradesXLSX, exportAnnotatedPDFs } from '../api';
import type { Student } from '../types';

interface Props {
  students: Student[];
}

export default function ExportPanel({ students }: Props) {
  const [error, setError] = useState('');
  const [loading, setLoading] = useState<string | null>(null);

  const handle = async (label: string, fn: () => Promise<void>) => {
    setError('');
    setLoading(label);
    try {
      await fn();
    } catch {
      setError(`Failed to export: ${label}`);
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="export-panel">
      <button
        onClick={() => handle('CSV', exportGradesCSV)}
        disabled={loading !== null}
        className="export-btn"
      >
        {loading === 'CSV' ? 'Exporting...' : '📊 Export CSV'}
      </button>
      <button
        onClick={() => handle('XLSX', exportGradesXLSX)}
        disabled={loading !== null}
        className="export-btn"
      >
        {loading === 'XLSX' ? 'Exporting...' : '📗 Export XLSX'}
      </button>
      <button
        onClick={() => handle('PDFs', () => exportAnnotatedPDFs(students))}
        disabled={loading !== null}
        className="export-btn"
      >
        {loading === 'PDFs' ? 'Exporting...' : '📄 Export Annotated PDFs'}
      </button>
      {error && <span className="export-error">{error}</span>}
    </div>
  );
}
