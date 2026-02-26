import { useState, useEffect } from 'react';
import { getConfig } from './api';
import type { SessionConfig, Student } from './types';
import SetupPage from './components/SetupPage';
import GradingView from './components/GradingView';

function App() {
  console.log('[App] render');
  const [session, setSession] = useState<SessionConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [currentStudent, setCurrentStudent] = useState<Student | null>(null);

  useEffect(() => {
    console.log('[App] useEffect: fetching config');
    const controller = new AbortController();
    getConfig(controller.signal)
      .then((cfg) => {
        console.log('[App] config fetched, configured:', cfg.configured, 'students:', cfg.students.length);
        setSession(cfg);
        if (cfg.configured && cfg.students.length > 0) {
          console.log('[App] auto-selecting first student:', cfg.students[0].student_number);
          setCurrentStudent(cfg.students[0]);
        }
        setLoading(false);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        console.error('[App] failed to fetch config:', err);
        setSession({ configured: false, students: [], grading_scheme: null, exams_dir: null });
        setLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    console.log('[App] currentStudent changed to:', currentStudent?.student_number ?? null);
  }, [currentStudent]);

  const handleConfigured = (cfg: SessionConfig) => {
    console.log('[App] handleConfigured: session configured, students:', cfg.students.length);
    setSession(cfg);
    if (cfg.students.length > 0) {
      console.log('[App] handleConfigured: auto-selecting first student:', cfg.students[0].student_number);
      setCurrentStudent(cfg.students[0]);
    }
  };

  if (loading) {
    return <div className="loading">Loading...</div>;
  }

  if (!session?.configured) {
    return <SetupPage onConfigured={handleConfigured} />;
  }

  return (
    <GradingView
      session={session}
      currentStudent={currentStudent}
      setCurrentStudent={setCurrentStudent}
    />
  );
}

export default App;
