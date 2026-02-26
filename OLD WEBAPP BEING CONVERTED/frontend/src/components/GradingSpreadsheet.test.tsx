import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import GradingSpreadsheet from './GradingSpreadsheet';
import type { Student, GradingScheme } from '../types';

vi.mock('../api', () => ({
  postGrade: vi.fn().mockResolvedValue(undefined),
}));

// Helpers to disambiguate from the new spreadsheet search input
const getGradeInput = () =>
  screen.getAllByRole('textbox').find((el) => el.classList.contains('grade-input'))!;
const queryGradeInput = () =>
  screen.queryAllByRole('textbox').find((el) => el.classList.contains('grade-input')) ?? null;

const students: Student[] = [
  { student_number: '1', last_name: 'Dupont', first_name: 'Alice' },
  { student_number: '2', last_name: 'Martin', first_name: 'Bob' },
];

const gradingScheme: GradingScheme = {
  exercises: [
    { name: 'Ex1', subquestions: [{ name: 'Q1', max_points: 4 }, { name: 'Q2', max_points: 6 }] },
  ],
};

function makeProps(overrides = {}) {
  return {
    students,
    gradingScheme,
    grades: {},
    currentStudent: students[0],
    onStudentSelect: vi.fn(),
    onGradeChange: vi.fn(),
    ...overrides,
  };
}

describe('GradingSpreadsheet', () => {
  it('renders student names and empty grade cells', () => {
    render(<GradingSpreadsheet {...makeProps()} />);
    expect(screen.getByText('Dupont, Alice')).toBeInTheDocument();
    expect(screen.getByText('Martin, Bob')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });

  it('clicking a grade cell opens an input without navigating the student', async () => {
    const onStudentSelect = vi.fn();
    render(<GradingSpreadsheet {...makeProps({ onStudentSelect })} />);

    await userEvent.click(screen.getAllByText('—')[0]);

    expect(getGradeInput()).toBeInTheDocument();
    expect(onStudentSelect).not.toHaveBeenCalled();
  });

  it('typing a value and pressing Enter saves the grade', async () => {
    const onGradeChange = vi.fn();
    render(<GradingSpreadsheet {...makeProps({ onGradeChange })} />);

    await userEvent.click(screen.getAllByText('—')[0]);
    await userEvent.type(getGradeInput(), '3.5');
    await userEvent.keyboard('{Enter}');

    expect(onGradeChange).toHaveBeenCalledWith('1', 'Q1', 3.5);
  });

  it('blurring with an invalid value does not call onGradeChange', async () => {
    const onGradeChange = vi.fn();
    render(<GradingSpreadsheet {...makeProps({ onGradeChange })} />);

    await userEvent.click(screen.getAllByText('—')[0]);
    await userEvent.type(getGradeInput(), 'abc');
    fireEvent.blur(getGradeInput());

    expect(onGradeChange).not.toHaveBeenCalled();
  });

  it('Escape closes the input without saving', async () => {
    const onGradeChange = vi.fn();
    render(<GradingSpreadsheet {...makeProps({ onGradeChange })} />);

    await userEvent.click(screen.getAllByText('—')[0]);
    expect(getGradeInput()).toBeInTheDocument();

    await userEvent.keyboard('{Escape}');
    expect(queryGradeInput()).not.toBeInTheDocument();
    expect(onGradeChange).not.toHaveBeenCalled();
  });

  it('Tab moves focus to the next subquestion cell', async () => {
    const onGradeChange = vi.fn();
    render(<GradingSpreadsheet {...makeProps({ onGradeChange })} />);

    await userEvent.click(screen.getAllByText('—')[0]); // Q1, student 1
    await userEvent.type(getGradeInput(), '2');
    await userEvent.keyboard('{Tab}');

    expect(onGradeChange).toHaveBeenCalledWith('1', 'Q1', 2);
    // Q2 input now open
    expect(getGradeInput()).toBeInTheDocument();
  });

  it('Enter moves focus to the next student for the same subquestion', async () => {
    const onGradeChange = vi.fn();
    render(<GradingSpreadsheet {...makeProps({ onGradeChange })} />);

    await userEvent.click(screen.getAllByText('—')[0]); // Q1, student 1
    await userEvent.type(getGradeInput(), '3');
    await userEvent.keyboard('{Enter}');

    expect(onGradeChange).toHaveBeenCalledWith('1', 'Q1', 3);
    // student 2 / Q1 input now open
    expect(getGradeInput()).toBeInTheDocument();
  });

  it('displays saved grades from props', () => {
    const grades = { '1': { Q1: 3.5 } };
    render(<GradingSpreadsheet {...makeProps({ grades })} />);
    const cells = screen.getAllByText('3.5');
    // The grade value appears in both the cell span and the Total column
    expect(cells.length).toBeGreaterThanOrEqual(1);
    expect(cells.some((el) => el.classList.contains('grade-cell'))).toBe(true);
  });

  it('renders an invalid grade (exceeds max) with the invalid CSS class', () => {
    const grades = { '1': { Q1: 99 } }; // Q1 max is 4
    render(<GradingSpreadsheet {...makeProps({ grades })} />);
    const cell = screen.getByText('99');
    expect(cell).toHaveClass('invalid');
  });
});

describe('GradingSpreadsheet render stability (infinite re-render regression)', () => {
  function countRenders(spy: ReturnType<typeof vi.spyOn>) {
    return spy.mock.calls.filter(
      ([msg]) => typeof msg === 'string' && (msg as string).startsWith('[GradingSpreadsheet] render'),
    ).length;
  }

  it('renders exactly once on initial mount', () => {
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {});
    render(<GradingSpreadsheet {...makeProps()} />);
    expect(countRenders(spy)).toBe(1);
    spy.mockRestore();
  });

  it('re-renders at most twice when only currentStudent changes', () => {
    const { rerender } = render(<GradingSpreadsheet {...makeProps()} />);
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {});
    rerender(<GradingSpreadsheet {...makeProps({ currentStudent: students[1] })} />);
    expect(countRenders(spy)).toBeLessThanOrEqual(2);
    spy.mockRestore();
  });

  it('re-renders at most twice when grades prop updates', () => {
    const { rerender } = render(<GradingSpreadsheet {...makeProps()} />);
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {});
    rerender(<GradingSpreadsheet {...makeProps({ grades: { '1': { Q1: 3.5 } } })} />);
    expect(countRenders(spy)).toBeLessThanOrEqual(2);
    spy.mockRestore();
  });
});
