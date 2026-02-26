import type { AnnotationTool } from '../types';

interface Props {
  activeTool: AnnotationTool;
  setActiveTool: (tool: AnnotationTool) => void;
}

const tools: { key: AnnotationTool; label: string; emoji: string; shortcut: string }[] = [
  { key: 'checkmark', label: 'Checkmark', emoji: '✅', shortcut: 'V' },
  { key: 'cross', label: 'Cross', emoji: '❌', shortcut: 'X' },
  { key: 'text', label: 'Text', emoji: '📝', shortcut: 'T' },
  { key: 'line', label: 'Line', emoji: '📏', shortcut: 'L' },
  { key: 'arrow', label: 'Arrow', emoji: '➡️', shortcut: 'A' },
  { key: 'circle', label: 'Circle', emoji: '⭕', shortcut: 'O' },
  { key: 'eraser', label: 'Eraser', emoji: '🗑️', shortcut: 'E' },
];

export default function AnnotationToolbar({ activeTool, setActiveTool }: Props) {
  return (
    <div className="annotation-toolbar">
      {tools.map(({ key, label, emoji, shortcut }) => (
        <button
          key={key}
          className={`tool-btn ${activeTool === key ? 'active' : ''}`}
          onClick={() => setActiveTool(activeTool === key ? null : key)}
          title={`${label} (${shortcut})`}
        >
          {emoji} {label} <kbd>{shortcut}</kbd>
        </button>
      ))}
      {activeTool && (
        <span className="active-tool-label">Active: {activeTool}</span>
      )}
    </div>
  );
}
