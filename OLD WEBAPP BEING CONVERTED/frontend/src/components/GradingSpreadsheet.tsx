import { useState, useCallback, useRef, useMemo } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from '@tanstack/react-table';
import type { Student, GradingScheme } from '../types';
import { postGrade } from '../api';

const GRADE_SCALE = 20; // French 0-20 grading scale

interface Props {
  students: Student[];
  gradingScheme: GradingScheme;
  grades: Record<string, Record<string, number>>;
  currentStudent: Student | null;
  onStudentSelect: (s: Student) => void;
  onGradeChange: (studentNumber: string, subquestionName: string, points: number) => void;
}

interface RowData {
  student: Student;
  grades: Record<string, number | ''>;
  total: number;
  grade: number;
}

const columnHelper = createColumnHelper<RowData>();

export default function GradingSpreadsheet({
  students,
  gradingScheme,
  grades,
  currentStudent,
  onStudentSelect,
  onGradeChange,
}: Props) {
  console.log('[GradingSpreadsheet] render — currentStudent:', currentStudent?.student_number ?? null, 'students:', students.length);
  const [editingCell, setEditingCell] = useState<{ sn: string; sq: string } | null>(null);
  const [editValue, setEditValue] = useState('');
  const [search, setSearch] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingNav = useRef<{ sn: string; sq: string; val: string } | null>(null);

  const allSubquestions = useMemo(
    () => gradingScheme.exercises.flatMap((ex) => ex.subquestions),
    [gradingScheme]
  );
  const maxTotal = useMemo(
    () => allSubquestions.reduce((sum, sq) => sum + sq.max_points, 0),
    [allSubquestions]
  );

  const data: RowData[] = useMemo(() => students.map((student) => {
    const studentGrades = grades[student.student_number] ?? {};
    const gradeRow: Record<string, number | ''> = {};
    let total = 0;
    for (const sq of allSubquestions) {
      const val = studentGrades[sq.name];
      gradeRow[sq.name] = val !== undefined ? val : '';
      if (val !== undefined) total += val;
    }
    const grade = maxTotal > 0 ? Math.round((total / maxTotal) * GRADE_SCALE * 10) / 10 : 0;
    return { student, grades: gradeRow, total, grade };
  }), [students, grades, allSubquestions, maxTotal]);

  // Rows shown in the table (search-filtered)
  const filteredData = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return data;
    return data.filter(
      (row) =>
        row.student.student_number.includes(q) ||
        row.student.last_name.toLowerCase().includes(q) ||
        row.student.first_name.toLowerCase().includes(q)
    );
  }, [data, search]);

  // Average row — computed from ALL students regardless of filter.
  // Only students with at least one non-empty cell are included.
  // Empty cells of included students count as 0.
  const averageRow = useMemo(() => {
    const included = data.filter((row) =>
      allSubquestions.some((sq) => row.grades[sq.name] !== '')
    );
    if (included.length === 0) return null;
    const avgGrades: Record<string, number> = {};
    for (const sq of allSubquestions) {
      const sum = included.reduce((acc, row) => {
        const val = row.grades[sq.name];
        return acc + (val !== '' ? (val as number) : 0);
      }, 0);
      avgGrades[sq.name] = sum / included.length;
    }
    const avgTotal = Object.values(avgGrades).reduce((a, b) => a + b, 0);
    const avgGrade = maxTotal > 0 ? Math.round((avgTotal / maxTotal) * GRADE_SCALE * 10) / 10 : 0;
    return { grades: avgGrades, total: avgTotal, grade: avgGrade, count: included.length };
  }, [data, allSubquestions, maxTotal]);

  const saveGrade = useCallback(
    (studentNumber: string, subquestionName: string, points: number) => {
      console.log('[GradingSpreadsheet] saveGrade: student', studentNumber, 'subquestion', subquestionName, 'points', points);
      onGradeChange(studentNumber, subquestionName, points);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        console.log('[GradingSpreadsheet] saveGrade: posting grade to backend — student', studentNumber, 'subquestion', subquestionName, 'points', points);
        postGrade({ student_number: studentNumber, subquestion_name: subquestionName, points }).catch(
          console.error
        );
      }, 500);
    },
    [onGradeChange]
  );

  const openCell = useCallback((sn: string, sqName: string, currentVal: number | '') => {
    console.log('[GradingSpreadsheet] openCell: student', sn, 'subquestion', sqName, 'currentVal', currentVal);
    setEditingCell({ sn, sq: sqName });
    setEditValue(currentVal !== '' ? String(currentVal) : '');
  }, []);

  // Returns a background color for a grade cell: gray=empty, yellow→white by %
  function gradeColor(val: number | '', maxPoints: number): string {
    if (val === '') return '#e8e8e8';
    const pct = Math.min(1, Math.max(0, (val as number) / maxPoints));
    // 0% → rgb(255,249,196) ≈ #fff9c4  |  100% → rgb(255,255,255) white
    const g = Math.round(249 + (255 - 249) * pct);
    const b = Math.round(196 + (255 - 196) * pct);
    return `rgb(255,${g},${b})`;
  }

  const columns = useMemo(() => [
    columnHelper.accessor((row) => `${row.student.last_name}, ${row.student.first_name}`, {
      id: 'name',
      header: 'Student',
      cell: (info) => (
        <span
          className="student-name-cell"
          onClick={(e) => { e.stopPropagation(); onStudentSelect(info.row.original.student); }}
          title="Click to open PDF"
        >
          {info.getValue()}
        </span>
      ),
    }),
    columnHelper.accessor((row) => row.student.student_number, {
      id: 'student_number',
      header: 'Number',
      cell: (info) => info.getValue(),
    }),
    ...allSubquestions.map((sq) =>
      columnHelper.accessor((row) => row.grades[sq.name], {
        id: sq.name,
        header: () => (
          <>
            <div>{sq.name}</div>
            <div className="col-max-pts">/{sq.max_points}</div>
          </>
        ),
        cell: (info) => {
          const sn = info.row.original.student.student_number;
          const rowIdx = filteredData.findIndex((r) => r.student.student_number === sn);
          const colIdx = allSubquestions.findIndex((s) => s.name === sq.name);
          const isEditing = editingCell?.sn === sn && editingCell?.sq === sq.name;
          const val = info.getValue();
          const isInvalid =
            val !== '' && typeof val === 'number' && val > sq.max_points;

          const handleBlur = () => {
            const num = parseFloat(editValue);
            if (!isNaN(num) && num >= 0) {
              saveGrade(sn, sq.name, num);
            }
            if (pendingNav.current) {
              const nav = pendingNav.current;
              pendingNav.current = null;
              setEditingCell({ sn: nav.sn, sq: nav.sq });
              setEditValue(nav.val);
            } else {
              setEditingCell(null);
            }
          };

          const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
            if (e.key === 'Escape') {
              pendingNav.current = null;
              setEditingCell(null);
              return;
            }
            if (e.key === 'Enter' || e.key === 'Tab') {
              e.preventDefault();
              let nextRowIdx = rowIdx;
              let nextColIdx = colIdx;
              if (e.key === 'Tab' && !e.shiftKey) {
                nextColIdx++;
                if (nextColIdx >= allSubquestions.length) {
                  nextColIdx = 0;
                  nextRowIdx++;
                }
              } else if (e.key === 'Tab' && e.shiftKey) {
                nextColIdx--;
                if (nextColIdx < 0) {
                  nextColIdx = allSubquestions.length - 1;
                  nextRowIdx--;
                }
              } else {
                nextRowIdx++;
              }
              if (nextRowIdx >= 0 && nextRowIdx < filteredData.length) {
                const nextSn = filteredData[nextRowIdx].student.student_number;
                const nextSqName = allSubquestions[nextColIdx]?.name;
                if (nextSqName) {
                  const nextVal = filteredData[nextRowIdx].grades[nextSqName];
                  pendingNav.current = { sn: nextSn, sq: nextSqName, val: nextVal !== '' ? String(nextVal) : '' };
                }
              }
              (e.target as HTMLInputElement).blur();
            }
          };

          if (isEditing) {
            return (
              <input
                className={`grade-input ${isInvalid ? 'invalid' : ''}`}
                value={editValue}
                autoFocus
                onChange={(e) => setEditValue(e.target.value)}
                onBlur={handleBlur}
                onKeyDown={handleKeyDown}
                onClick={(e) => e.stopPropagation()}
              />
            );
          }

          return (
            <span className={`grade-cell ${isInvalid ? 'invalid' : ''}`}>
              {val !== '' ? val : '—'}
            </span>
          );
        },
      })
    ),
    columnHelper.accessor('total', {
      header: 'Total',
      cell: (info) => info.getValue().toFixed(1),
    }),
    columnHelper.accessor('grade', {
      header: 'Grade (/20)',
      cell: (info) => info.getValue().toFixed(1),
    }),
  ], [allSubquestions, filteredData, editingCell, editValue, saveGrade, openCell, onStudentSelect]);

  const table = useReactTable({
    data: filteredData,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  // Build exercise header groups
  const exerciseHeaders = useMemo<{ name: string; colSpan: number; key: string }[]>(() => [
    { name: '', colSpan: 2, key: '__meta__' },
    ...gradingScheme.exercises.map((ex) => ({
      name: ex.name,
      colSpan: ex.subquestions.length,
      key: ex.name,
    })),
    { name: '', colSpan: 2, key: '__totals__' },
  ], [gradingScheme]);

  return (
    <div className="spreadsheet-container">
      <div className="spreadsheet-filter-bar">
        <input
          type="text"
          className="spreadsheet-search"
          placeholder="Filter students by name or number…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <span className="spreadsheet-filter-count">
            {filteredData.length} / {data.length} student{data.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>
      <div className="spreadsheet-wrapper">
        <table className="grading-table">
          <thead>
            <tr>
              {exerciseHeaders.map((eh, idx) => (
                <th
                  key={eh.key}
                  colSpan={eh.colSpan}
                  className={[eh.name ? 'exercise-group-header' : '', idx === 0 ? 'sticky-col' : ''].filter(Boolean).join(' ') || undefined}
                >
                  {eh.name}
                </th>
              ))}
            </tr>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    className={header.column.id === 'name' ? 'sticky-col' : undefined}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const isCurrent = row.original.student.student_number === currentStudent?.student_number;
              return (
                <tr
                  key={row.id}
                  className={isCurrent ? 'current-student-row' : ''}
                  onClick={() => {
                    console.log('[GradingSpreadsheet] row clicked: onStudentSelect for student', row.original.student.student_number);
                    onStudentSelect(row.original.student);
                  }}
                  style={{ cursor: 'pointer' }}
                >
                  {row.getVisibleCells().map((cell) => {
                    const sq = allSubquestions.find((s) => s.name === cell.column.id);
                    const isNameCol = cell.column.id === 'name';
                    const gradeVal = sq ? row.original.grades[sq.name] : undefined;
                    const isInvalidTd = sq && gradeVal !== '' && gradeVal !== undefined && (gradeVal as number) > sq.max_points;
                    const tdStyle = sq
                      ? { background: isInvalidTd ? '#ffcdd2' : gradeColor(gradeVal ?? '', sq.max_points) }
                      : undefined;
                    return (
                      <td
                        key={cell.id}
                        className={[isNameCol ? 'sticky-col' : undefined, sq ? 'grade-col' : undefined].filter(Boolean).join(' ') || undefined}
                        style={tdStyle}
                        onClick={sq ? (e) => {
                          e.stopPropagation();
                          const isAlreadyEditing =
                            editingCell?.sn === row.original.student.student_number &&
                            editingCell?.sq === sq.name;
                          if (!isAlreadyEditing) {
                            openCell(row.original.student.student_number, sq.name, gradeVal ?? '');
                          }
                        } : undefined}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
          {averageRow && (
            <tfoot>
              <tr className="average-row">
                <td className="sticky-col">Avg ({averageRow.count})</td>
                <td />
                {allSubquestions.map((sq) => (
                  <td key={sq.name}>{averageRow.grades[sq.name].toFixed(1)}</td>
                ))}
                <td>{averageRow.total.toFixed(1)}</td>
                <td>{averageRow.grade.toFixed(1)}</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
