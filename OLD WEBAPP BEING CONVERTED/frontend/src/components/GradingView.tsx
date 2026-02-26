import { useState, useEffect, useRef, useCallback } from 'react';
import type { SessionConfig, Student, Annotation, AnnotationTool } from '../types';
import { getGrades, getAnnotations, postAnnotations } from '../api';
import StudentNavigation from './StudentNavigation';
import PdfViewer from './PdfViewer';
import AnnotationToolbar from './AnnotationToolbar';
import GradingSpreadsheet from './GradingSpreadsheet';
import ExportPanel from './ExportPanel';

interface Props {
  session: SessionConfig;
  currentStudent: Student | null;
  setCurrentStudent: (s: Student) => void;
}

export default function GradingView({ session, currentStudent, setCurrentStudent }: Props) {
  console.log('[GradingView] render — currentStudent:', currentStudent?.student_number ?? null);
  const [grades, setGrades] = useState<Record<string, Record<string, number>>>({});
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [activeTool, setActiveTool] = useState<AnnotationTool>(null);
  const [error, setError] = useState('');
  const [leftWidth, setLeftWidth] = useState(50);
  const isDragging = useRef(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const annotationSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    dragStartX.current = e.clientX;
    dragStartWidth.current = leftWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [leftWidth]);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return;
      const containerWidth = containerRef.current.offsetWidth;
      const delta = e.clientX - dragStartX.current;
      const newWidth = Math.max(20, Math.min(80, dragStartWidth.current + (delta / containerWidth) * 100));
      setLeftWidth(newWidth);
    };
    const handleMouseUp = () => {
      if (!isDragging.current) return;
      isDragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  useEffect(() => {
    console.log('[GradingView] grades useEffect: loading grades');
    const controller = new AbortController();
    const t0 = performance.now();
    getGrades(controller.signal)
      .then((g) => {
        console.log('[GradingView] grades useEffect: loaded in', (performance.now() - t0).toFixed(1), 'ms, students with grades:', Object.keys(g).length);
        setGrades(g);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        console.error('[GradingView] grades useEffect: failed to load grades', err);
        setError('Failed to load grades');
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    console.log('[GradingView] annotations useEffect fired — currentStudent:', currentStudent?.student_number ?? null);
    if (!currentStudent) return;
    const controller = new AbortController();
    const t0 = performance.now();
    console.log('[GradingView] annotations useEffect: fetching annotations for', currentStudent.student_number);
    getAnnotations(currentStudent.student_number, controller.signal)
      .then((anns) => {
        console.log('[GradingView] annotations useEffect: loaded', anns.length, 'annotations in', (performance.now() - t0).toFixed(1), 'ms for student', currentStudent.student_number);
        setAnnotations(anns);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        console.warn('[GradingView] annotations useEffect: failed to load annotations for', currentStudent.student_number, err);
        setAnnotations([]);
      });
    return () => controller.abort();
  }, [currentStudent]);

  const handleAnnotationsChange = useCallback(
    (updated: Annotation[]) => {
      console.log('[GradingView] handleAnnotationsChange: saving', updated.length, 'annotations for student', currentStudent?.student_number);
      setAnnotations(updated);
      if (currentStudent) {
        if (annotationSaveTimerRef.current) clearTimeout(annotationSaveTimerRef.current);
        annotationSaveTimerRef.current = setTimeout(() => {
          postAnnotations(currentStudent.student_number, updated).catch((err) => {
            console.error('[GradingView] handleAnnotationsChange: failed to save annotations', err);
            setError('Failed to save annotations');
          });
        }, 300);
      }
    },
    [currentStudent]
  );

  const handleSetCurrentStudent = useCallback((s: Student) => {
    console.log('[GradingView] setCurrentStudent called from StudentNavigation with student:', s.student_number);
    setCurrentStudent(s);
  }, [setCurrentStudent]);

  const handleGradeChange = useCallback((studentNumber: string, subquestionName: string, points: number) => {
    console.log('[GradingView] handleGradeChange: student', studentNumber, 'subquestion', subquestionName, 'points', points);
    setGrades((prev) => ({
      ...prev,
      [studentNumber]: {
        ...(prev[studentNumber] ?? {}),
        [subquestionName]: points,
      },
    }));
  }, []);

  if (!session.grading_scheme) return <div>No grading scheme loaded.</div>;

  return (
    <div className="grading-view">
      {error && <div className="error-banner">{error}</div>}
      <div className="grading-top-bar">
        <StudentNavigation
          students={session.students}
          currentStudent={currentStudent}
          setCurrentStudent={handleSetCurrentStudent}
        />
        <ExportPanel students={session.students} />
      </div>
      <div className="grading-main" ref={containerRef}>
        <div className="left-panel" style={{ width: `${leftWidth}%` }}>
          <AnnotationToolbar activeTool={activeTool} setActiveTool={setActiveTool} />
          {currentStudent ? (() => {
            const idx = session.students.findIndex((s) => s.student_number === currentStudent.student_number);
            const prev = idx > 0 ? session.students[idx - 1].student_number : undefined;
            const next = idx !== -1 && idx < session.students.length - 1 ? session.students[idx + 1].student_number : undefined;
            return (
              <PdfViewer
                studentNumber={currentStudent.student_number}
                prevStudentNumber={prev}
                nextStudentNumber={next}
                annotations={annotations}
                activeTool={activeTool}
                setActiveTool={setActiveTool}
                onAnnotationsChange={handleAnnotationsChange}
              />
            );
          })() : (
            <div className="no-student">Select a student to view their exam.</div>
          )}
        </div>
        <div className="panel-divider" onMouseDown={handleDividerMouseDown} />
        <div className="right-panel">
          <GradingSpreadsheet
            students={session.students}
            gradingScheme={session.grading_scheme}
            grades={grades}
            currentStudent={currentStudent}
            onStudentSelect={setCurrentStudent}
            onGradeChange={handleGradeChange}
          />
        </div>
      </div>
    </div>
  );
}
