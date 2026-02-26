export interface Student {
  student_number: string;
  last_name: string;
  first_name: string;
}

export interface Subquestion {
  name: string;
  max_points: number;
}

export interface Exercise {
  name: string;
  subquestions: Subquestion[];
}

export interface GradingScheme {
  exercises: Exercise[];
}

export interface Annotation {
  id: string;
  student_number: string;
  page: number;
  type: 'checkmark' | 'cross' | 'text' | 'line' | 'arrow' | 'circle';
  x: number;
  y: number;
  text?: string;
  x2?: number;
  y2?: number;
  width?: number;
}

export interface GradeEntry {
  student_number: string;
  subquestion_name: string;
  points: number;
}

export interface SessionConfig {
  configured: boolean;
  students: Student[];
  grading_scheme: GradingScheme | null;
  exams_dir: string | null;
}

export type AnnotationTool = 'checkmark' | 'cross' | 'text' | 'line' | 'arrow' | 'circle' | 'eraser' | null;
