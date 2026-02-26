import { render, act } from '@testing-library/react';
import { vi } from 'vitest';
import GradingView from './GradingView';
import type { SessionConfig, Student } from '../types';

vi.mock('../api', () => ({
  getGrades: vi.fn().mockResolvedValue({}),
  getAnnotations: vi.fn().mockResolvedValue([]),
  postAnnotations: vi.fn().mockResolvedValue(undefined),
  getExamUrl: vi.fn((sn: string) => `/api/exams/${sn}`),
}));

// Capture every onGradeChange reference GradingSpreadsheet receives.
const capturedOnGradeChange: Array<(sn: string, sq: string, pts: number) => void> = [];

vi.mock('./GradingSpreadsheet', () => ({
  default: (props: {
    onGradeChange: (sn: string, sq: string, pts: number) => void;
    [key: string]: unknown;
  }) => {
    capturedOnGradeChange.push(props.onGradeChange);
    return <div data-testid="grading-spreadsheet" />;
  },
}));

vi.mock('./PdfViewer', () => ({ default: () => <div /> }));
vi.mock('./AnnotationToolbar', () => ({ default: () => <div /> }));
vi.mock('./ExportPanel', () => ({ default: () => <div /> }));
vi.mock('./StudentNavigation', () => ({
  default: ({ students: ss, setCurrentStudent }: {
    students: Student[];
    setCurrentStudent: (s: Student) => void;
  }) => (
    <button data-testid="nav-next" onClick={() => setCurrentStudent(ss[1])}>
      Next
    </button>
  ),
}));

const students: Student[] = [
  { student_number: '1', last_name: 'Dupont', first_name: 'Alice' },
  { student_number: '2', last_name: 'Martin', first_name: 'Bob' },
];

const session: SessionConfig = {
  configured: true,
  students,
  grading_scheme: {
    exercises: [{ name: 'Ex1', subquestions: [{ name: 'Q1', max_points: 4 }] }],
  },
  exams_dir: '/exams',
};

describe('GradingView callback stability (infinite re-render regression)', () => {
  beforeEach(() => {
    capturedOnGradeChange.length = 0;
  });

  it('passes the same handleGradeChange reference to GradingSpreadsheet on every render', async () => {
    const setCurrentStudent = vi.fn();
    const { rerender } = render(
      <GradingView session={session} currentStudent={students[0]} setCurrentStudent={setCurrentStudent} />,
    );

    // Let async effects (getGrades, getAnnotations) settle
    await act(async () => {});

    // Simulate switching students — GradingView re-renders with a new currentStudent
    rerender(
      <GradingView session={session} currentStudent={students[1]} setCurrentStudent={setCurrentStudent} />,
    );
    await act(async () => {});

    // Every render of GradingView should pass the exact same onGradeChange reference
    // to GradingSpreadsheet (useCallback with [] deps makes it stable).
    expect(capturedOnGradeChange.length).toBeGreaterThanOrEqual(2);
    const first = capturedOnGradeChange[0];
    for (const ref of capturedOnGradeChange) {
      expect(ref).toBe(first);
    }
  });
});
