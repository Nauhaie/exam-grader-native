import { useState, useEffect, useRef, useCallback } from 'react';
import * as pdfjs from 'pdfjs-dist';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import type { Annotation, AnnotationTool } from '../types';
import { getExamUrl } from '../api';

const { MissingPDFException } = pdfjs as unknown as { MissingPDFException: new (...args: unknown[]) => Error };

pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.js', import.meta.url).toString();

// Module-level cache so documents survive React re-renders and student navigation
const docCache = new Map<string, PDFDocumentProxy>();
const loadingCache = new Map<string, Promise<PDFDocumentProxy>>();
const pageRenderCache = new Map<string, ImageBitmap>();
const getPageCacheKey = (student: string, page: number, scale: number) => `${student}-${page}-${scale}`;

async function preRenderAndCache(studentNumber: string, pageNumber: number, scale: number): Promise<PDFDocumentProxy | null> {
  const cacheKey = getPageCacheKey(studentNumber, pageNumber, scale);
  // If the page is already rendered and cached, we don't need to do anything.
  // We still return the loaded document so the caller can update the page count.
  if (pageRenderCache.has(cacheKey)) {
    return loadDocument(getExamUrl(studentNumber)).catch(() => null);
  }

  try {
    console.log(`[PdfViewer] ⚡️ PRE-RENDER START — student ${studentNumber} page ${pageNumber}`);
    const url = getExamUrl(studentNumber);
    const pdf = await loadDocument(url);

    // It's possible the page was rendered by the main view while we were loading the document.
    // If so, we can abort the pre-render.
    if (pageRenderCache.has(cacheKey)) {
      console.log(`[PdfViewer] ⚡️ PRE-RENDER ABORT (was rendered concurrently) — student ${studentNumber} page ${pageNumber}`);
      return pdf;
    }

    const page = await pdf.getPage(pageNumber);
    const viewport = page.getViewport({ scale });

    // Render to an in-memory canvas.
    const canvas = document.createElement('canvas');
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.imageSmoothingEnabled = false; // Disable for performance on scanned images

    await page.render({ canvasContext: ctx, viewport }).promise;

    const imageBitmap = await createImageBitmap(canvas);
    pageRenderCache.set(cacheKey, imageBitmap);
    console.log(`[PdfViewer] ⚡️ PRE-RENDER DONE — student ${studentNumber} page ${pageNumber}`);
    return pdf;
  } catch (err) {
    // It's okay if pre-rendering fails; it's a non-critical optimization.
    console.warn(`[PdfViewer] Pre-render failed for student ${studentNumber}:`, err);
    return null;
  }
}


function loadDocument(url: string): Promise<PDFDocumentProxy> {
  const cached = docCache.get(url);
  if (cached) return Promise.resolve(cached);
  const inflight = loadingCache.get(url);
  if (inflight) return inflight;
  const promise = pdfjs.getDocument(url).promise.then((doc) => {
    docCache.set(url, doc);
    loadingCache.delete(url);
    return doc;
  }).catch((err) => {
    loadingCache.delete(url);
    throw err;
  });
  loadingCache.set(url, promise);
  return promise;
}

interface Props {
  studentNumber: string;
  prevStudentNumber?: string;
  nextStudentNumber?: string;
  annotations: Annotation[];
  activeTool: AnnotationTool;
  setActiveTool: (tool: AnnotationTool) => void;
  onAnnotationsChange: (annotations: Annotation[]) => void;
}

type DragTarget =
  | { type: 'point'; id: string }
  | { type: 'line-start'; id: string }
  | { type: 'line-end'; id: string }
  | { type: 'circle-move'; id: string; origX: number; origY: number; origX2: number; origY2: number; startMouseX: number; startMouseY: number }
  | { type: 'text-resize'; id: string; startMouseX: number; origWidth: number };

export default function PdfViewer({ studentNumber, prevStudentNumber, nextStudentNumber, annotations, activeTool, setActiveTool, onAnnotationsChange }: Props) {
  // numPages is tracked per student so pre-loaded documents remember their page count
  const [numPagesMap, setNumPagesMap] = useState<Record<string, number>>({});
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1.2);
  const [pdfStatus, setPdfStatus] = useState<null | 'missing' | 'error'>(null);
  const [textInput, setTextInput] = useState('');
  const [pendingPos, setPendingPos] = useState<{ x: number; y: number } | null>(null);
  const [lineStart, setLineStart] = useState<{ x: number; y: number } | null>(null);
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null);
  const [editingAnnotationId, setEditingAnnotationId] = useState<string | null>(null);
  const [dragging, setDragging] = useState<DragTarget | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderTaskRef = useRef<import('pdfjs-dist/types/src/display/api').RenderTask | null>(null);
  const isHovered = useRef(false);

  const numPages = numPagesMap[studentNumber] ?? 0;

  // Render current page to canvas whenever student/page/scale changes
  useEffect(() => {
    if (!canvasRef.current) return;
    let cancelled = false;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d')!;

    const url = getExamUrl(studentNumber);
    const studentNumPages = numPagesMap[studentNumber] ?? 0;
    const safePageNumber = Math.min(pageNumber, studentNumPages || 999) || 1;
    const cacheKey = getPageCacheKey(studentNumber, safePageNumber, scale);

    const cachedRender = pageRenderCache.get(cacheKey);
    if (cachedRender) {
      console.log(`[PdfViewer] ✅ CACHE HIT — student ${studentNumber} page ${safePageNumber} scale ${scale}`);
      canvas.width = cachedRender.width;
      canvas.height = cachedRender.height;
      ctx.drawImage(cachedRender, 0, 0);
      return;
    }

    const t0 = performance.now();
    console.log(`[PdfViewer] ⬇ FETCH START — student ${studentNumber}`);
    loadDocument(url)
      .then(async (pdf) => {
        if (cancelled) return;
        const elapsed = (performance.now() - t0).toFixed(1);
        console.log(`[PdfViewer] ✅ FETCH DONE — student ${studentNumber} — numPages: ${pdf.numPages} — ${elapsed}ms`);
        setNumPagesMap((m) => (m[studentNumber] === pdf.numPages ? m : { ...m, [studentNumber]: pdf.numPages }));

        const actualPageNumber = Math.min(pageNumber, pdf.numPages) || 1;
        const actualCacheKey = getPageCacheKey(studentNumber, actualPageNumber, scale);
        const recheckedCachedRender = pageRenderCache.get(actualCacheKey);
        if (recheckedCachedRender) {
          console.log(`[PdfViewer] ✅ CACHE HIT (re-checked) — student ${studentNumber} page ${actualPageNumber} scale ${scale}`);
          canvas.width = recheckedCachedRender.width;
          canvas.height = recheckedCachedRender.height;
          ctx.drawImage(recheckedCachedRender, 0, 0);
          return;
        }

        const page = await pdf.getPage(actualPageNumber);
        if (cancelled) return;

        const viewport = page.getViewport({ scale });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        const ctx = canvas.getContext('2d')!;
        ctx.imageSmoothingEnabled = false; // Disable for performance on scanned images

        const renderT0 = performance.now();
        console.log(`[PdfViewer] 🖨 RENDER START — student ${studentNumber} page ${actualPageNumber} scale ${scale}`);
        try {
          renderTaskRef.current = page.render({ canvasContext: ctx, viewport });
          await renderTaskRef.current.promise;
          if (cancelled) return;

          const renderElapsed = (performance.now() - renderT0).toFixed(1);
          console.log(`[PdfViewer] ✅ RENDER DONE — student ${studentNumber} page ${actualPageNumber} scale ${scale} — ${renderElapsed}ms`);
          console.log(`[PdfViewer] CACHE WRITE — student ${studentNumber} page ${actualPageNumber} scale ${scale}`);
          createImageBitmap(canvas).then((imageBitmap) => {
            pageRenderCache.set(actualCacheKey, imageBitmap);
          });
        } catch (err: any) {
          if (err?.name === 'RenderingCancelledException') {
            console.log(`[PdfViewer] Render cancelled for student ${studentNumber} page ${actualPageNumber}`);
          } else if (!cancelled) {
            throw err;
          }
        } finally {
          renderTaskRef.current = null;
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.error('[PdfViewer] onLoadError: failed to load PDF for student', studentNumber, err);
          setPdfStatus(err instanceof MissingPDFException ? 'missing' : 'error');
        }
      });

    return () => {
      cancelled = true;
      if (renderTaskRef.current) {
        renderTaskRef.current.cancel();
        console.log(`[PdfViewer] Cleanup: cancelled render for student ${studentNumber} page ${safePageNumber}`);
      }
    };
  }, [studentNumber, pageNumber, scale, numPagesMap]);

  // Pre-load and pre-render neighbour documents in the background
  useEffect(() => {
    for (const sn of [prevStudentNumber, nextStudentNumber]) {
      if (!sn) continue;
      // Pre-render the first page since it's the most likely to be viewed next.
      preRenderAndCache(sn, 1, scale).then((pdf) => {
        // After pre-rendering, update the page count map for the UI.
        if (pdf) {
          setNumPagesMap((m) => (m[sn] === pdf.numPages ? m : { ...m, [sn]: pdf.numPages }));
        }
      });
    }
  }, [prevStudentNumber, nextStudentNumber, scale]);

  useEffect(() => {
    console.log('[PdfViewer] studentNumber useEffect fired — new studentNumber:', studentNumber, 'resetting state');
    setPdfStatus(null);
    setPageNumber(1);
    setLineStart(null);
    setMousePos(null);
    setEditingAnnotationId(null);
    setDragging(null);
    console.log('[PdfViewer] studentNumber useEffect: state reset complete for', studentNumber);
  }, [studentNumber]);

  // Clear in-progress line/arrow/circle when tool changes away from those tools
  useEffect(() => {
    if (activeTool !== 'line' && activeTool !== 'arrow' && activeTool !== 'circle') {
      setLineStart(null);
      setMousePos(null);
    }
  }, [activeTool]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      if (e.key === 'Escape') {
        if (lineStart) {
          console.log('[PdfViewer] keydown Escape: clearing lineStart');
          setLineStart(null); setMousePos(null); e.preventDefault();
        }
        return;
      }

      let tool: AnnotationTool = null;
      if (e.key === 'v' || e.key === 'V') tool = 'checkmark';
      else if (e.key === 'x' || e.key === 'X') tool = 'cross';
      else if (e.key === 't' || e.key === 'T') tool = 'text';
      else if (e.key === 'l' || e.key === 'L') tool = 'line';
      else if (e.key === 'a' || e.key === 'A') tool = 'arrow';
      else if (e.key === 'o' || e.key === 'O') tool = 'circle';
      else if (e.key === 'e' || e.key === 'E') tool = 'eraser';
      else return;
      e.preventDefault();
      const newTool = activeTool === tool ? null : tool;
      console.log('[PdfViewer] keydown: switching tool from', activeTool, 'to', newTool, '(key:', e.key, ')');
      setActiveTool(newTool);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeTool, setActiveTool, lineStart]);

  const handleOverlayClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (dragging) return; // ignore click if we just finished a drag
      if (!activeTool || !overlayRef.current) return;
      // When actively drawing a line/arrow/circle (lineStart is set), allow clicks on
      // existing annotations to fall through so the shape can be completed at that position.
      const isCompletingShape = lineStart && (activeTool === 'line' || activeTool === 'arrow' || activeTool === 'circle');
      if (!isCompletingShape && (e.target as HTMLElement).closest('.annotation-marker')) return;
      if (activeTool === 'eraser') return;

      const rect = overlayRef.current.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;

      if (activeTool === 'line' || activeTool === 'arrow' || activeTool === 'circle') {
        if (!lineStart) {
          console.log('[PdfViewer] handleOverlayClick: setting lineStart at', { x, y });
          setLineStart({ x, y });
        } else {
          console.log('[PdfViewer] handleOverlayClick: completing', activeTool, 'from', lineStart, 'to', { x, y });
          const annotation: Annotation = {
            id: crypto.randomUUID(),
            student_number: studentNumber,
            page: pageNumber,
            type: activeTool,
            x: lineStart.x,
            y: lineStart.y,
            x2: x,
            y2: y,
          };
          onAnnotationsChange([...annotations, annotation]);
          setLineStart(null);
          setMousePos(null);
        }
        return;
      }

      if (activeTool === 'text') {
        // If there is already a pending text input open, ignore further clicks
        // so the user must finish (Enter/Add) or cancel (Escape) the current one first.
        if (pendingPos || editingAnnotationId) return;
        console.log('[PdfViewer] handleOverlayClick: setting pendingPos for text at', { x, y });
        setPendingPos({ x, y });
        return;
      }

      console.log('[PdfViewer] handleOverlayClick: adding', activeTool, 'annotation at', { x, y });
      const annotation: Annotation = {
        id: crypto.randomUUID(),
        student_number: studentNumber,
        page: pageNumber,
        type: activeTool as 'checkmark' | 'cross',
        x,
        y,
      };
      onAnnotationsChange([...annotations, annotation]);
      setActiveTool(null);
    },
    [activeTool, annotations, dragging, editingAnnotationId, lineStart, onAnnotationsChange, pageNumber, pendingPos, studentNumber]
  );

  const handleOverlayMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!overlayRef.current) return;
      const rect = overlayRef.current.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;

      if (dragging) {
        if (dragging.type === 'circle-move') {
          const dx = x - dragging.startMouseX;
          const dy = y - dragging.startMouseY;
          onAnnotationsChange(
            annotations.map((a) =>
              a.id !== dragging.id
                ? a
                : { ...a, x: dragging.origX + dx, y: dragging.origY + dy, x2: dragging.origX2 + dx, y2: dragging.origY2 + dy }
            )
          );
          return;
        }
        if (dragging.type === 'text-resize') {
          const dx = x - dragging.startMouseX;
          const newWidth = Math.max(0.02, dragging.origWidth + dx);
          onAnnotationsChange(
            annotations.map((a) => (a.id !== dragging.id ? a : { ...a, width: newWidth }))
          );
          return;
        }
        onAnnotationsChange(
          annotations.map((a) => {
            if (a.id !== dragging.id) return a;
            if (dragging.type === 'point') return { ...a, x, y };
            if (dragging.type === 'line-start') return { ...a, x, y };
            if (dragging.type === 'line-end') return { ...a, x2: x, y2: y };
            return a;
          })
        );
        return;
      }

      if ((activeTool === 'line' || activeTool === 'arrow' || activeTool === 'circle') && lineStart) {
        setMousePos({ x, y });
      }
    },
    [activeTool, annotations, dragging, lineStart, onAnnotationsChange]
  );

  const handleOverlayMouseUp = useCallback(() => {
    if (dragging) {
      setDragging(null);
    }
  }, [dragging]);

  // Clear drag state when the mouse button is released anywhere (e.g. outside the overlay).
  useEffect(() => {
    const handleGlobalMouseUp = () => { if (dragging) setDragging(null); };
    window.addEventListener('mouseup', handleGlobalMouseUp);
    return () => window.removeEventListener('mouseup', handleGlobalMouseUp);
  }, [dragging]);

  const handleAnnotationMouseDown = useCallback(
    (e: React.MouseEvent, ann: Annotation, target: 'point' | 'line-start' | 'line-end' = 'point') => {
      if (activeTool && activeTool !== 'text') return; // only drag when no tool active (or text tool)
      e.stopPropagation();
      e.preventDefault();
      setDragging({ type: target, id: ann.id });
    },
    [activeTool]
  );

  const handleAddText = () => {
    if (!pendingPos || !textInput.trim()) return;
    console.log('[PdfViewer] handleAddText: adding text annotation at', pendingPos, 'text:', textInput.trim());
    const annotation: Annotation = {
      id: crypto.randomUUID(),
      student_number: studentNumber,
      page: pageNumber,
      type: 'text',
      x: pendingPos.x,
      y: pendingPos.y,
      text: textInput.trim(),
    };
    onAnnotationsChange([...annotations, annotation]);
    setPendingPos(null);
    setTextInput('');
    setActiveTool(null);
  };

  const handleSaveEditedText = () => {
    if (!textInput.trim() || !editingAnnotationId) return;
    console.log('[PdfViewer] handleSaveEditedText: saving edited text for annotation', editingAnnotationId);
    onAnnotationsChange(
      annotations.map((a) => (a.id === editingAnnotationId ? { ...a, text: textInput.trim() } : a))
    );
    setEditingAnnotationId(null);
    setTextInput('');
    setActiveTool(null);
  };

  const handleDeleteAnnotation = (id: string) => {
    console.log('[PdfViewer] handleDeleteAnnotation: deleting annotation', id);
    onAnnotationsChange(annotations.filter((a) => a.id !== id));
  };

  const handleAnnotationClick = useCallback(
    (e: React.MouseEvent, ann: Annotation) => {
      if (dragging) return;
      // When actively drawing a line/arrow/circle, let the click pass through to the
      // overlay so it completes the shape at this position instead of selecting the annotation.
      if (lineStart && (activeTool === 'line' || activeTool === 'arrow' || activeTool === 'circle')) return;
      e.stopPropagation();
      if (activeTool === 'eraser') {
        console.log('[PdfViewer] handleAnnotationClick: erasing annotation', ann.id, ann.type);
        handleDeleteAnnotation(ann.id);
      } else if (activeTool === 'text' && ann.type === 'text') {
        console.log('[PdfViewer] handleAnnotationClick: editing text annotation', ann.id);
        setEditingAnnotationId(ann.id);
        setTextInput(ann.text ?? '');
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activeTool, annotations, dragging, lineStart, onAnnotationsChange]
  );

  const pageAnnotations = annotations.filter((a) => a.page === pageNumber);
  const lineAnnotations = pageAnnotations.filter((a) => a.type === 'line' || a.type === 'arrow');
  const circleAnnotations = pageAnnotations.filter((a) => a.type === 'circle');
  const pointAnnotations = pageAnnotations.filter((a) => a.type !== 'line' && a.type !== 'arrow' && a.type !== 'circle');

  const canDrag = !activeTool || activeTool === 'text';
  const overlayCursor = dragging ? 'grabbing' : activeTool === 'eraser' ? 'not-allowed' : activeTool ? 'crosshair' : 'default';

  return (
    <div className="pdf-viewer" onMouseEnter={() => { isHovered.current = true; }} onMouseLeave={() => { isHovered.current = false; }}>
      <div className="pdf-controls">
        <button onClick={() => { console.log('[PdfViewer] Prev page clicked, current:', pageNumber); setPageNumber((p) => Math.max(1, p - 1)); }} disabled={pageNumber <= 1}>
          ← Prev
        </button>
        <span>
          Page {pageNumber} / {numPages}
        </span>
        <button onClick={() => { console.log('[PdfViewer] Next page clicked, current:', pageNumber); setPageNumber((p) => Math.min(numPages, p + 1)); }} disabled={pageNumber >= numPages}>
          Next →
        </button>
        <button onClick={() => setScale((s) => Math.max(0.5, s - 0.2))}>−</button>
        <span>{Math.round(scale * 100)}%</span>
        <button onClick={() => setScale((s) => Math.min(3, s + 0.2))}>+</button>
      </div>

      <div className="pdf-container">
        <div className="pdf-page-wrapper">
          {pdfStatus === 'missing' ? (
            <div className="pdf-missing">
              <p>📄 No PDF found for student #{studentNumber}</p>
              <p>Upload <code>{studentNumber}.pdf</code> to the exams directory to grade this student.</p>
            </div>
          ) : pdfStatus === 'error' ? (
            <div className="pdf-error">
              <p>⚠️ Could not load PDF for student #{studentNumber}</p>
              <p>Make sure the file <code>{studentNumber}.pdf</code> exists in the exams directory.</p>
            </div>
          ) : (
            // Inner wrapper sized exactly to the canvas so the annotation overlay
            // covers only the PDF page (not the full container width).  This ensures
            // annotation fractions are computed relative to the actual page dimensions,
            // which fixes annotation positions in exported PDFs.
            <div style={{ position: 'relative', display: 'inline-block' }}>
              <canvas ref={canvasRef} />
              <div
                ref={overlayRef}
                className="annotation-overlay"
                style={{ cursor: overlayCursor }}
                onClick={handleOverlayClick}
                onMouseMove={handleOverlayMouseMove}
                onMouseUp={handleOverlayMouseUp}
              >
                  {/* SVG layer for line/arrow annotations */}
                  <svg className="annotation-lines-svg">
                    <defs>
                      <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
                        <polygon points="0 0, 8 3, 0 6" fill="red" />
                      </marker>
                      <marker id="arrowhead-hover" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
                        <polygon points="0 0, 8 3, 0 6" fill="#ff4444" />
                      </marker>
                    </defs>
                    {lineAnnotations.map((ann) => (
                      <g key={ann.id}>
                        <line
                          x1={`${ann.x * 100}%`}
                          y1={`${ann.y * 100}%`}
                          x2={`${(ann.x2 ?? ann.x) * 100}%`}
                          y2={`${(ann.y2 ?? ann.y) * 100}%`}
                          stroke="red"
                          strokeWidth="2"
                          strokeLinecap="round"
                          markerEnd={ann.type === 'arrow' ? 'url(#arrowhead)' : undefined}
                          className={`line-annotation${activeTool === 'eraser' ? ' line-annotation--erasable' : ''}`}
                          style={{ pointerEvents: activeTool === 'eraser' ? 'stroke' : canDrag ? 'stroke' : 'none', cursor: canDrag && !activeTool ? 'grab' : undefined }}
                          onClick={(e) => { e.stopPropagation(); if (activeTool === 'eraser') handleDeleteAnnotation(ann.id); }}
                          onMouseDown={(e) => handleAnnotationMouseDown(e as unknown as React.MouseEvent, ann, 'point')}
                        />
                        {/* Drag handles for line endpoints */}
                        {canDrag && !activeTool && (
                          <>
                            <circle
                              cx={`${ann.x * 100}%`}
                              cy={`${ann.y * 100}%`}
                              r="6"
                              fill="red"
                              fillOpacity="0.5"
                              style={{ cursor: 'grab', pointerEvents: 'all' }}
                              onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); setDragging({ type: 'line-start', id: ann.id }); }}
                            />
                            <circle
                              cx={`${(ann.x2 ?? ann.x) * 100}%`}
                              cy={`${(ann.y2 ?? ann.y) * 100}%`}
                              r="6"
                              fill="red"
                              fillOpacity="0.5"
                              style={{ cursor: 'grab', pointerEvents: 'all' }}
                              onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); setDragging({ type: 'line-end', id: ann.id }); }}
                            />
                          </>
                        )}
                      </g>
                    ))}
                    {/* Circle annotations */}
                    {circleAnnotations.map((ann) => {
                      const ow = overlayRef.current?.clientWidth ?? 1;
                      const oh = overlayRef.current?.clientHeight ?? 1;
                      const dx = ((ann.x2 ?? ann.x) - ann.x) * ow;
                      const dy = ((ann.y2 ?? ann.y) - ann.y) * oh;
                      const r = Math.sqrt(dx * dx + dy * dy);
                      return (
                        <g key={ann.id}>
                          <circle
                            cx={`${ann.x * 100}%`}
                            cy={`${ann.y * 100}%`}
                            r={r}
                            fill="none"
                            stroke="red"
                            strokeWidth="2"
                            className={activeTool === 'eraser' ? 'line-annotation--erasable' : ''}
                            style={{ pointerEvents: activeTool === 'eraser' ? 'all' : canDrag ? 'all' : 'none', cursor: canDrag && !activeTool ? 'grab' : undefined }}
                            onClick={(e) => { e.stopPropagation(); if (activeTool === 'eraser') handleDeleteAnnotation(ann.id); }}
                            onMouseDown={(e) => {
                              if (activeTool && activeTool !== 'text') return;
                              e.stopPropagation();
                              e.preventDefault();
                              const rect = overlayRef.current!.getBoundingClientRect();
                              const mouseX = (e.clientX - rect.left) / rect.width;
                              const mouseY = (e.clientY - rect.top) / rect.height;
                              setDragging({ type: 'circle-move', id: ann.id, origX: ann.x, origY: ann.y, origX2: ann.x2 ?? ann.x, origY2: ann.y2 ?? ann.y, startMouseX: mouseX, startMouseY: mouseY });
                            }}
                          />
                          {/* Drag handle for edge (resize) */}
                          {canDrag && !activeTool && (
                            <circle
                              cx={`${(ann.x2 ?? ann.x) * 100}%`}
                              cy={`${(ann.y2 ?? ann.y) * 100}%`}
                              r="6"
                              fill="red"
                              fillOpacity="0.5"
                              style={{ cursor: 'grab', pointerEvents: 'all' }}
                              onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); setDragging({ type: 'line-end', id: ann.id }); }}
                            />
                          )}
                        </g>
                      );
                    })}
                    {/* Preview line/arrow while drawing */}
                    {(activeTool === 'line' || activeTool === 'arrow') && lineStart && mousePos && (
                      <line
                        x1={`${lineStart.x * 100}%`}
                        y1={`${lineStart.y * 100}%`}
                        x2={`${mousePos.x * 100}%`}
                        y2={`${mousePos.y * 100}%`}
                        stroke="red"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeDasharray="6 4"
                        markerEnd={activeTool === 'arrow' ? 'url(#arrowhead)' : undefined}
                        style={{ pointerEvents: 'none' }}
                      />
                    )}
                    {/* Preview circle while drawing */}
                    {activeTool === 'circle' && lineStart && mousePos && (() => {
                      const ow = overlayRef.current?.clientWidth ?? 1;
                      const oh = overlayRef.current?.clientHeight ?? 1;
                      const dx = (mousePos.x - lineStart.x) * ow;
                      const dy = (mousePos.y - lineStart.y) * oh;
                      const r = Math.sqrt(dx * dx + dy * dy);
                      return (
                        <circle
                          cx={`${lineStart.x * 100}%`}
                          cy={`${lineStart.y * 100}%`}
                          r={r}
                          fill="none"
                          stroke="red"
                          strokeWidth="2"
                          strokeDasharray="6 4"
                          style={{ pointerEvents: 'none' }}
                        />
                      );
                    })()}
                    {lineStart && (
                      <circle
                        cx={`${lineStart.x * 100}%`}
                        cy={`${lineStart.y * 100}%`}
                        r="4"
                        fill="red"
                        style={{ pointerEvents: 'none' }}
                      />
                    )}
                  </svg>

                  {pointAnnotations.map((ann) => (
                    <div
                      key={ann.id}
                      className={`annotation-marker${activeTool === 'eraser' ? ' annotation-marker--erasable' : ''}${canDrag && !activeTool ? ' annotation-marker--draggable' : ''}`}
                      style={{ left: `${ann.x * 100}%`, top: `${ann.y * 100}%` }}
                      onClick={(e) => handleAnnotationClick(e, ann)}
                      onMouseDown={(e) => handleAnnotationMouseDown(e, ann)}
                      title={
                        activeTool === 'eraser'
                          ? 'Click to delete'
                          : activeTool === 'text' && ann.type === 'text'
                          ? 'Click to edit'
                          : !activeTool
                          ? 'Drag to move'
                          : undefined
                      }
                    >
                      {ann.type === 'checkmark' && (
                        <svg width="24" height="18" viewBox="-12 -9 24 18" style={{ display: 'block', overflow: 'visible' }}>
                          <line x1="-10" y1="0" x2="-3" y2="7" stroke="rgb(0,153,0)" strokeWidth="2" strokeLinecap="round"/>
                          <line x1="-3" y1="7" x2="10" y2="-5" stroke="rgb(0,153,0)" strokeWidth="2" strokeLinecap="round"/>
                        </svg>
                      )}
                      {ann.type === 'cross' && (
                        <svg width="20" height="20" viewBox="-10 -10 20 20" style={{ display: 'block', overflow: 'visible' }}>
                          <line x1="-8" y1="-8" x2="8" y2="8" stroke="rgb(217,25,25)" strokeWidth="2" strokeLinecap="round"/>
                          <line x1="8" y1="-8" x2="-8" y2="8" stroke="rgb(217,25,25)" strokeWidth="2" strokeLinecap="round"/>
                        </svg>
                      )}
                      {ann.type === 'text' && (
                        <>
                          <span
                            className="text-annotation"
                            style={ann.width ? { display: 'inline-block', width: `${ann.width * (overlayRef.current?.clientWidth ?? 1)}px`, wordBreak: 'break-word' } : undefined}
                          >
                            {ann.text}
                          </span>
                          {canDrag && !activeTool && (
                            <span
                              className="text-resize-handle"
                              onMouseDown={(e) => {
                                e.stopPropagation();
                                e.preventDefault();
                                const rect = overlayRef.current!.getBoundingClientRect();
                                const mouseX = (e.clientX - rect.left) / rect.width;
                                setDragging({ type: 'text-resize', id: ann.id, startMouseX: mouseX, origWidth: ann.width ?? (e.currentTarget.parentElement!.offsetWidth / rect.width) });
                              }}
                              title="Drag to resize"
                            />
                          )}
                        </>
                      )}
                    </div>
                  ))}

                  {pendingPos && (
                    <div
                      className="text-input-popup"
                      style={{ left: `${pendingPos.x * 100}%`, top: `${pendingPos.y * 100}%` }}
                    >
                      <input
                        autoFocus
                        value={textInput}
                        onChange={(e) => setTextInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleAddText();
                          if (e.key === 'Escape') {
                            setPendingPos(null);
                            setTextInput('');
                          }
                        }}
                        placeholder="Enter text..."
                      />
                      <button onClick={handleAddText}>Add</button>
                      <button onClick={() => { setPendingPos(null); setTextInput(''); }}>Cancel</button>
                    </div>
                  )}

                  {editingAnnotationId && (() => {
                    const ann = annotations.find((a) => a.id === editingAnnotationId);
                    if (!ann) return null;
                    return (
                      <div
                        className="text-input-popup"
                        style={{ left: `${ann.x * 100}%`, top: `${ann.y * 100}%` }}
                      >
                        <input
                          autoFocus
                          value={textInput}
                          onChange={(e) => setTextInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSaveEditedText();
                            if (e.key === 'Escape') { setEditingAnnotationId(null); setTextInput(''); }
                          }}
                          placeholder="Edit text..."
                        />
                        <button onClick={handleSaveEditedText}>Save</button>
                        <button onClick={() => { setEditingAnnotationId(null); setTextInput(''); }}>Cancel</button>
                      </div>
                    );
                  })()}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
