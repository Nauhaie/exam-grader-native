import axios, { isCancel } from 'axios';
import { PDFDocument, rgb, StandardFonts, degrees } from 'pdf-lib';
import JSZip from 'jszip';
import type { SessionConfig, Student, Annotation, GradeEntry, GradingScheme } from '../types';

const api = axios.create({ baseURL: '/api' });

// Request interceptor: log every outgoing request with a start timestamp
api.interceptors.request.use((config) => {
  const t0 = performance.now();
  (config as unknown as Record<string, unknown>)._t0 = t0;
  console.log('[API] REQUEST', config.method?.toUpperCase(), config.url, { params: config.params, data: config.data });
  return config;
});

// Response interceptor: log every response with status and elapsed time
api.interceptors.response.use(
  (response) => {
    const t0 = (response.config as unknown as Record<string, unknown>)._t0 as number | undefined;
    const elapsed = t0 !== undefined ? (performance.now() - t0).toFixed(1) : '?';
    console.log('[API] RESPONSE', response.config.method?.toUpperCase(), response.config.url, 'status:', response.status, `(${elapsed}ms)`);
    return response;
  },
  (error) => {
    if (isCancel(error)) {
      return Promise.reject(error);
    }
    const cfg = error.config ?? {};
    const t0 = (cfg as unknown as Record<string, unknown>)._t0 as number | undefined;
    const elapsed = t0 !== undefined ? (performance.now() - t0).toFixed(1) : '?';
    console.error('[API] ERROR', cfg.method?.toUpperCase(), cfg.url, 'status:', error.response?.status, `(${elapsed}ms)`, error.message);
    return Promise.reject(error);
  }
);

export async function getConfig(signal?: AbortSignal): Promise<SessionConfig> {
  console.log('[API] getConfig: start');
  const t0 = performance.now();
  const res = await api.get<SessionConfig>('/config', { signal });
  console.log('[API] getConfig: done in', (performance.now() - t0).toFixed(1), 'ms, configured:', res.data.configured);
  return res.data;
}

export async function postConfig(config: {
  exams_dir: string;
  students_csv: string;
  grading_scheme: string;
}): Promise<SessionConfig> {
  console.log('[API] postConfig: start', config);
  const t0 = performance.now();
  const res = await api.post<SessionConfig>('/config', config);
  console.log('[API] postConfig: done in', (performance.now() - t0).toFixed(1), 'ms');
  return res.data;
}

export async function getStudents(): Promise<Student[]> {
  console.log('[API] getStudents: start');
  const t0 = performance.now();
  const res = await api.get<Student[]>('/students');
  console.log('[API] getStudents: done in', (performance.now() - t0).toFixed(1), 'ms, count:', res.data.length);
  return res.data;
}

export async function getGrades(signal?: AbortSignal): Promise<Record<string, Record<string, number>>> {
  console.log('[API] getGrades: start');
  const t0 = performance.now();
  const res = await api.get<Record<string, Record<string, number>>>('/grades', { signal });
  console.log('[API] getGrades: done in', (performance.now() - t0).toFixed(1), 'ms, students with grades:', Object.keys(res.data).length);
  return res.data;
}

export async function postGrade(grade: GradeEntry): Promise<void> {
  console.log('[API] postGrade: start', grade);
  const t0 = performance.now();
  await api.post('/grades', grade);
  console.log('[API] postGrade: done in', (performance.now() - t0).toFixed(1), 'ms');
}

export async function getAnnotations(studentNumber: string, signal?: AbortSignal): Promise<Annotation[]> {
  console.log('[API] getAnnotations: start for student', studentNumber);
  const t0 = performance.now();
  const res = await api.get<Annotation[]>(`/annotations/${studentNumber}`, { signal });
  console.log('[API] getAnnotations: done in', (performance.now() - t0).toFixed(1), 'ms, count:', res.data.length);
  return res.data;
}

export async function postAnnotations(studentNumber: string, annotations: Annotation[]): Promise<void> {
  console.log('[API] postAnnotations: start for student', studentNumber, 'count:', annotations.length);
  const t0 = performance.now();
  await api.post(`/annotations/${studentNumber}`, annotations);
  console.log('[API] postAnnotations: done in', (performance.now() - t0).toFixed(1), 'ms');
}

export async function deleteAnnotation(studentNumber: string, annotationId: string): Promise<void> {
  console.log('[API] deleteAnnotation: start student', studentNumber, 'annotationId:', annotationId);
  const t0 = performance.now();
  await api.delete(`/annotations/${studentNumber}/${annotationId}`);
  console.log('[API] deleteAnnotation: done in', (performance.now() - t0).toFixed(1), 'ms');
}

export function getExamUrl(studentNumber: string): string {
  return `/api/exams/${studentNumber}`;
}

export async function exportGradesCSV(): Promise<void> {
  console.log('[API] exportGradesCSV: start');
  const res = await api.get('/export/grades/csv', { responseType: 'blob' });
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'grades.csv';
  a.click();
  URL.revokeObjectURL(url);
  console.log('[API] exportGradesCSV: done');
}

export async function exportGradesXLSX(): Promise<void> {
  console.log('[API] exportGradesXLSX: start');
  const res = await api.get('/export/grades/xlsx', { responseType: 'blob' });
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'grades.xlsx';
  a.click();
  URL.revokeObjectURL(url);
  console.log('[API] exportGradesXLSX: done');
}

// Convert normalized display-space fractions to PDF page coordinates,
// accounting for the page's rotation (0, 90, 180, or 270 degrees CW).
function toPageCoords(
  fx: number, fy: number,
  width: number, height: number,
  rotation: number
): { x: number; y: number } {
  if (rotation === 90) {
    // Display: width=h, height=w. Display (fx,fy) → PDF (fy*w, fx*h)
    return { x: fy * width, y: fx * height };
  } else if (rotation === 180) {
    return { x: (1 - fx) * width, y: fy * height };
  } else if (rotation === 270) {
    // Display: width=h, height=w. Display (fx,fy) → PDF ((1-fy)*w, (1-fx)*h)
    return { x: (1 - fy) * width, y: (1 - fx) * height };
  }
  // rotation === 0 (default): PDF y-axis is bottom-up, annotations are top-down
  return { x: fx * width, y: (1 - fy) * height };
}

async function bakeAnnotationsIntoPdf(studentNumber: string, annotations: Annotation[]): Promise<Uint8Array> {
  const pdfBytes = await fetch(getExamUrl(studentNumber)).then((r) => r.arrayBuffer());
  const pdfDoc = await PDFDocument.load(pdfBytes);
  const pages = pdfDoc.getPages();
  const font = await pdfDoc.embedFont(StandardFonts.Helvetica);

  for (const ann of annotations) {
    const page = pages[ann.page - 1];
    if (!page) continue;
    const { width, height } = page.getSize();
    const rotation = page.getRotation().angle;
    const { x: px, y: py } = toPageCoords(ann.x, ann.y, width, height, rotation);

    if (ann.type === 'checkmark') {
      // Draw a green checkmark using two lines (matches UI SVG shape)
      const s = 10;
      page.drawLine({ start: { x: px - s, y: py }, end: { x: px - s * 0.3, y: py - s * 0.7 }, color: rgb(0, 0.6, 0), thickness: 2 });
      page.drawLine({ start: { x: px - s * 0.3, y: py - s * 0.7 }, end: { x: px + s, y: py + s * 0.5 }, color: rgb(0, 0.6, 0), thickness: 2 });
    } else if (ann.type === 'cross') {
      // Draw a red X using two diagonal lines (matches UI SVG shape)
      const s = 8;
      page.drawLine({ start: { x: px - s, y: py - s }, end: { x: px + s, y: py + s }, color: rgb(0.85, 0.1, 0.1), thickness: 2 });
      page.drawLine({ start: { x: px + s, y: py - s }, end: { x: px - s, y: py + s }, color: rgb(0.85, 0.1, 0.1), thickness: 2 });
    } else if (ann.type === 'text' && ann.text) {
      const textMaxWidth = ann.width != null ? ann.width * width : 150;
      // Estimate the rendered text dimensions so we can draw a yellow background first.
      const fontSize = 11;
      const lineHeightPx = 13;
      const singleLineWidth = font.widthOfTextAtSize(ann.text, fontSize);
      const numLines = singleLineWidth > textMaxWidth ? Math.max(1, Math.ceil(singleLineWidth / textMaxWidth)) : 1;
      const bgWidth = (numLines === 1 ? singleLineWidth : textMaxWidth) + 8;
      const bgHeight = numLines * lineHeightPx + 4;
      // In PDF coords y is bottom-up; text baseline is at py; subsequent lines go downward.
      page.drawRectangle({
        x: px - 4,
        y: py - (numLines - 1) * lineHeightPx - 3,
        width: bgWidth,
        height: bgHeight,
        color: rgb(1, 1, 0),
        opacity: 0.4,
        borderWidth: 0,
      });
      page.drawText(ann.text, {
        x: px, y: py, size: fontSize, color: rgb(0, 0, 0), font, maxWidth: textMaxWidth, lineHeight: lineHeightPx,
        rotate: rotation !== 0 ? degrees(rotation) : undefined,
      });
    } else if ((ann.type === 'line' || ann.type === 'arrow') && ann.x2 !== undefined && ann.y2 !== undefined) {
      const { x: px2, y: py2 } = toPageCoords(ann.x2, ann.y2, width, height, rotation);
      page.drawLine({ start: { x: px, y: py }, end: { x: px2, y: py2 }, color: rgb(0.85, 0.1, 0.1), thickness: 2 });
      if (ann.type === 'arrow') {
        // Draw a small arrowhead triangle at the end point
        const dx = px2 - px;
        const dy = py2 - py;
        const len = Math.sqrt(dx * dx + dy * dy) || 1;
        const ux = dx / len;
        const uy = dy / len;
        const size = 10;
        const lx = px2 - ux * size - uy * size * 0.5;
        const ly = py2 - uy * size + ux * size * 0.5;
        const rx = px2 - ux * size + uy * size * 0.5;
        const ry = py2 - uy * size - ux * size * 0.5;
        page.drawLine({ start: { x: px2, y: py2 }, end: { x: lx, y: ly }, color: rgb(0.85, 0.1, 0.1), thickness: 2 });
        page.drawLine({ start: { x: px2, y: py2 }, end: { x: rx, y: ry }, color: rgb(0.85, 0.1, 0.1), thickness: 2 });
      }
    } else if (ann.type === 'circle' && ann.x2 !== undefined && ann.y2 !== undefined) {
      const { x: px2, y: py2 } = toPageCoords(ann.x2, ann.y2, width, height, rotation);
      const r = Math.sqrt((px2 - px) ** 2 + (py2 - py) ** 2);
      page.drawEllipse({ x: px, y: py, xScale: r, yScale: r, borderColor: rgb(0.85, 0.1, 0.1), borderWidth: 2 });
    }
  }

  return pdfDoc.save();
}

export async function exportAnnotatedPDFs(students: Student[]): Promise<void> {
  console.log('[API] exportAnnotatedPDFs: start — students:', students.length);
  const zip = new JSZip();

  await Promise.all(
    students.map(async (student) => {
      const sn = student.student_number;
      try {
        const annotations = await getAnnotations(sn);
        const pdfBytes = await bakeAnnotationsIntoPdf(sn, annotations);
        zip.file(`${sn}_annotated.pdf`, pdfBytes);
        console.log('[API] exportAnnotatedPDFs: baked annotations for student', sn);
      } catch (err) {
        console.warn('[API] exportAnnotatedPDFs: skipping student', sn, '—', err);
      }
    })
  );

  const blob = await zip.generateAsync({ type: 'blob' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'annotated_exams.zip';
  a.click();
  URL.revokeObjectURL(url);
  console.log('[API] exportAnnotatedPDFs: done');
}

export async function getGradingScheme(): Promise<GradingScheme> {
  console.log('[API] getGradingScheme: start');
  const t0 = performance.now();
  const res = await api.get<GradingScheme>('/grading-scheme');
  console.log('[API] getGradingScheme: done in', (performance.now() - t0).toFixed(1), 'ms');
  return res.data;
}

export async function postGradingScheme(scheme: GradingScheme): Promise<GradingScheme> {
  console.log('[API] postGradingScheme: start');
  const t0 = performance.now();
  const res = await api.post<GradingScheme>('/grading-scheme', scheme);
  console.log('[API] postGradingScheme: done in', (performance.now() - t0).toFixed(1), 'ms');
  return res.data;
}

export async function getSampleGradingScheme(): Promise<GradingScheme> {
  console.log('[API] getSampleGradingScheme: start');
  const t0 = performance.now();
  const res = await api.get<GradingScheme>('/grading-scheme/sample');
  console.log('[API] getSampleGradingScheme: done in', (performance.now() - t0).toFixed(1), 'ms');
  return res.data;
}
