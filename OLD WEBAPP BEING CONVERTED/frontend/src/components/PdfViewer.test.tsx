import { render, screen, act, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import PdfViewer from './PdfViewer';
import type { AnnotationTool } from '../types';

const makePage = () => ({
  getViewport: ({ scale }: { scale: number }) => ({ width: 800 * scale, height: 1100 * scale }),
  render: () => ({ promise: Promise.resolve() }),
});

const makePdfDoc = (numPages = 2) => ({
  numPages,
  getPage: (_n: number) => Promise.resolve(makePage()),
});

vi.mock('pdfjs-dist', () => {
  // Define MissingPDFException inside the factory so the same class is shared
  // between PdfViewer (which destructures it from pdfjs) and our tests.
  class MissingPDFException extends Error {
    constructor(message: string) { super(message); this.name = 'MissingPDFException'; }
  }
  return {
    GlobalWorkerOptions: { workerSrc: '' },
    MissingPDFException,
    getDocument: vi.fn((_args: unknown) => ({
      promise: Promise.resolve(makePdfDoc()),
    })),
  };
});

vi.mock('../api', () => ({
  getExamUrl: (sn: string) => `/api/exams/${sn}`,
}));

// Import after mock so we get the mocked version
import * as pdfjs from 'pdfjs-dist';

function makeProps(overrides = {}) {
  return {
    studentNumber: '42',
    annotations: [],
    activeTool: null as AnnotationTool,
    setActiveTool: vi.fn(),
    onAnnotationsChange: vi.fn(),
    ...overrides,
  };
}

// Helper: reject with a MissingPDFException for the next getDocument call
function mockMissingPdf() {
  const MissingPDFExceptionCls = (pdfjs as unknown as { MissingPDFException: new (m: string) => Error }).MissingPDFException;
  vi.mocked(pdfjs.getDocument).mockReturnValueOnce({
    promise: Promise.reject(new MissingPDFExceptionCls('Missing PDF')),
  } as ReturnType<typeof pdfjs.getDocument>);
}

// Helper: reject with a generic error for the next getDocument call
function mockPdfError() {
  vi.mocked(pdfjs.getDocument).mockReturnValueOnce({
    promise: Promise.reject(new Error('Network error')),
  } as ReturnType<typeof pdfjs.getDocument>);
}

describe('PdfViewer', () => {
  beforeEach(() => {
    vi.mocked(pdfjs.getDocument).mockImplementation((_args) => ({
      promise: Promise.resolve(makePdfDoc()),
    }));
  });

  it('renders a canvas when load succeeds', async () => {
    const { container } = render(<PdfViewer {...makeProps()} />);
    await waitFor(() => expect(container.querySelector('canvas')).toBeInTheDocument());
    expect(screen.queryByText(/Could not load PDF/)).not.toBeInTheDocument();
    expect(screen.queryByText(/No PDF found/)).not.toBeInTheDocument();
  });

  it('renders only a single canvas for the current page', async () => {
    const { container } = render(<PdfViewer {...makeProps()} />);
    await waitFor(() => {
      const canvases = container.querySelectorAll('canvas');
      expect(canvases.length).toBe(1);
    });
  });

  it('loads pdfjs worker from local bundle instead of CDN', () => {
    const workerSrc = (pdfjs.GlobalWorkerOptions as { workerSrc: string }).workerSrc;
    expect(workerSrc).not.toContain('unpkg.com');
    expect(workerSrc).not.toContain('cdnjs.cloudflare.com');
  });

  it('shows an error message when PDF fails to load', async () => {
    mockPdfError();
    render(<PdfViewer {...makeProps({ studentNumber: 'sn-load-error' })} />);
    await waitFor(() =>
      expect(screen.getByText(/Could not load PDF for student #sn-load-error/)).toBeInTheDocument()
    );
  });

  it('shows a friendly missing PDF message when the file does not exist', async () => {
    mockMissingPdf();
    render(<PdfViewer {...makeProps({ studentNumber: 'sn-missing' })} />);
    await waitFor(() =>
      expect(screen.getByText(/No PDF found for student #sn-missing/)).toBeInTheDocument()
    );
    expect(screen.queryByText(/Could not load PDF/)).not.toBeInTheDocument();
  });

  it('clears the error when studentNumber changes', async () => {
    mockPdfError();
    const { rerender } = render(<PdfViewer {...makeProps({ studentNumber: 'sn-err-clear' })} />);
    await waitFor(() => expect(screen.getByText(/Could not load PDF/)).toBeInTheDocument());

    await act(async () => {
      rerender(<PdfViewer {...makeProps({ studentNumber: 'sn-good-after-err' })} />);
    });
    expect(screen.queryByText(/Could not load PDF/)).not.toBeInTheDocument();
    expect(screen.queryByText(/No PDF found/)).not.toBeInTheDocument();
  });

  it('shows the student number in the error message', async () => {
    mockPdfError();
    render(<PdfViewer {...makeProps({ studentNumber: '1234-err' })} />);
    await waitFor(() =>
      expect(screen.getByText(/student #1234-err/)).toBeInTheDocument()
    );
  });

  it('uses canvas for rendering (no separate text or annotation layers)', async () => {
    const { container } = render(<PdfViewer {...makeProps()} />);
    await waitFor(() => expect(container.querySelector('canvas')).toBeInTheDocument());
    // Direct canvas rendering has no separate pdfjs text/annotation layer elements
    expect(container.querySelector('.textLayer')).not.toBeInTheDocument();
    expect(container.querySelector('.annotationLayer')).not.toBeInTheDocument();
  });

  it('deactivates the text tool after adding text via the text input popup', async () => {
    const setActiveTool = vi.fn();
    const onAnnotationsChange = vi.fn();
    const { container } = render(
      <PdfViewer
        {...makeProps({ activeTool: 'text' as AnnotationTool, setActiveTool, onAnnotationsChange })}
      />,
    );

    // Simulate clicking the overlay to open the text input popup.
    // jsdom doesn't support getBoundingClientRect so we need fireEvent.
    const overlay = container.querySelector('.annotation-overlay');
    expect(overlay).toBeTruthy();
    await act(async () => {
      overlay!.dispatchEvent(
        new MouseEvent('click', { bubbles: true, clientX: 50, clientY: 50 }),
      );
    });

    // A text input popup should appear
    const input = screen.getByPlaceholderText('Enter text...');
    expect(input).toBeInTheDocument();

    // Type text using fireEvent
    const { fireEvent } = await import('@testing-library/react');
    await act(async () => {
      fireEvent.change(input, { target: { value: 'Hello' } });
    });
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' });
    });

    // After adding text, setActiveTool(null) should have been called
    expect(setActiveTool).toHaveBeenCalledWith(null);
  });
});
