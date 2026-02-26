import { useState, useRef, useEffect } from 'react';
import type { Student } from '../types';

interface Props {
  students: Student[];
  currentStudent: Student | null;
  setCurrentStudent: (s: Student) => void;
}

export default function StudentNavigation({ students, currentStudent, setCurrentStudent }: Props) {
  console.log('[StudentNavigation] render — currentStudent:', currentStudent?.student_number ?? null, 'total students:', students.length);
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const filtered = students.filter(
    (s) =>
      s.student_number.includes(search) ||
      s.last_name.toLowerCase().includes(search.toLowerCase()) ||
      s.first_name.toLowerCase().includes(search.toLowerCase())
  );

  const currentIndex = currentStudent
    ? students.findIndex((s) => s.student_number === currentStudent.student_number)
    : -1;

  console.log('[StudentNavigation] filtered list length:', filtered.length, 'currentIndex:', currentIndex);

  const goTo = (index: number) => {
    console.log('[StudentNavigation] goTo called with index:', index, '— students.length:', students.length);
    if (index >= 0 && index < students.length) {
      const target = students[index];
      console.log('[StudentNavigation] goTo: calling setCurrentStudent with student:', target.student_number, target.last_name, target.first_name);
      setCurrentStudent(target);
    } else {
      console.warn('[StudentNavigation] goTo: index out of bounds, ignoring');
    }
  };

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setSearch('');
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Focus search input when dropdown opens; scroll active item into view
  useEffect(() => {
    if (isOpen) {
      searchRef.current?.focus();
      // Scroll the currently selected student into view after a paint
      requestAnimationFrame(() => {
        const active = listRef.current?.querySelector<HTMLLIElement>('.student-dropdown-item--active');
        active?.scrollIntoView({ block: 'nearest' });
      });
    }
  }, [isOpen]);

  const handleSelect = (s: Student) => {
    console.log('[StudentNavigation] handleSelect: student', s.student_number);
    setCurrentStudent(s);
    setIsOpen(false);
    setSearch('');
  };

  const dropdownLabel = currentStudent
    ? `${currentStudent.last_name}, ${currentStudent.first_name} #${currentStudent.student_number}`
    : 'Select student…';

  return (
    <div className="student-navigation">
      <button
        onClick={() => { console.log('[StudentNavigation] Prev button clicked, currentIndex:', currentIndex); goTo(currentIndex - 1); }}
        disabled={currentIndex <= 0}
        className="nav-btn"
        title="Previous student"
      >
        ← Prev
      </button>

      <div className="student-dropdown" ref={dropdownRef}>
        <button
          className="student-dropdown-btn"
          onClick={() => setIsOpen((o) => !o)}
          title="Select student from list"
        >
          <span className="student-dropdown-label">{dropdownLabel}</span>
          <span className="student-dropdown-counter">
            {currentIndex >= 0 ? `${currentIndex + 1} / ${students.length}` : `0 / ${students.length}`}
          </span>
          <span className="student-dropdown-arrow">{isOpen ? '▲' : '▼'}</span>
        </button>

        {isOpen && (
          <div className="student-dropdown-panel">
            <input
              ref={searchRef}
              type="text"
              className="student-dropdown-search"
              placeholder="Search by name or number…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') { setIsOpen(false); setSearch(''); }
              }}
            />
            <ul className="student-dropdown-list" ref={listRef}>
              {filtered.length === 0 && (
                <li className="student-dropdown-empty">No students found</li>
              )}
              {filtered.map((s) => (
                <li
                  key={s.student_number}
                  className={`student-dropdown-item${s.student_number === currentStudent?.student_number ? ' student-dropdown-item--active' : ''}`}
                  onClick={() => handleSelect(s)}
                >
                  <span className="student-dropdown-item-name">{s.last_name}, {s.first_name}</span>
                  <span className="student-dropdown-item-num">#{s.student_number}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <button
        onClick={() => { console.log('[StudentNavigation] Next button clicked, currentIndex:', currentIndex); goTo(currentIndex + 1); }}
        disabled={currentIndex >= students.length - 1}
        className="nav-btn"
        title="Next student"
      >
        Next →
      </button>
    </div>
  );
}
