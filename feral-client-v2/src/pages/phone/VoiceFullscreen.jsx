/**
 * VoiceFullscreen stub — placeholder until Subagent C delivers the real component.
 * Exports the minimal API surface D's ChatPanel relies on.
 */
export default function VoiceFullscreen({ open, onClose, initialMode }) {
  if (!open) return null;
  return (
    <div data-testid="voice-fullscreen" data-mode={initialMode}>
      <button type="button" onClick={onClose}>Close</button>
    </div>
  );
}
