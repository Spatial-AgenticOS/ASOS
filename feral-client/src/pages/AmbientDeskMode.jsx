import { Brain } from 'lucide-react';

export default function AmbientDeskMode({ lastMemory }) {
  return (
    <div className="flex flex-col items-center gap-3">
      {lastMemory && (
        <div className="max-w-sm text-center">
          <div className="flex items-center gap-2 justify-center mb-1">
            <Brain size={12} className="text-feral-accent" />
            <span className="text-[9px] text-feral-text-muted uppercase tracking-wider">Last Memory</span>
          </div>
          <p className="text-sm text-feral-text-secondary leading-relaxed italic">"{lastMemory}"</p>
        </div>
      )}
    </div>
  );
}
