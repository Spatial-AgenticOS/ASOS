import { useState, useEffect } from 'react';
import { Moon, BookOpen, CheckCircle2 } from 'lucide-react';
import { API_BASE } from '../config';

export default function AmbientWindDownMode({ time }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/ambient/wind_down`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setData(d); })
      .catch(() => {});
  }, []);

  return (
    <div className="flex flex-col items-center gap-5 max-w-md text-center px-4">
      {/* Bedtime countdown */}
      {data?.sleep_prep?.time_to_bed_min != null && (
        <div className="flex items-center gap-2 text-purple-300">
          <Moon size={14} />
          <span className="text-sm">{data.sleep_prep.time_to_bed_min} min until bedtime</span>
        </div>
      )}

      {/* Day recap */}
      {data?.day_recap?.completed_tasks?.length > 0 && (
        <div className="w-full">
          <h3 className="text-[10px] text-feral-text-muted uppercase tracking-wider mb-2">
            Today you completed
          </h3>
          <div className="space-y-1">
            {data.day_recap.completed_tasks.map((t, i) => (
              <div key={i} className="flex items-center gap-2 text-sm text-feral-text-secondary">
                <CheckCircle2 size={12} className="text-purple-400 shrink-0" />
                <span>{t.title || t}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Episodes / memorable moments */}
      {data?.episodes?.length > 0 && (
        <div className="w-full">
          <h3 className="text-[10px] text-feral-text-muted uppercase tracking-wider mb-2">
            Memorable moments
          </h3>
          {data.episodes.map((e, i) => (
            <blockquote
              key={i}
              className="text-sm text-purple-200/70 italic border-l-2 border-purple-500/30 pl-3 my-2 text-left"
            >
              {e.summary}
            </blockquote>
          ))}
        </div>
      )}

      {/* Sleep hints */}
      {data?.sleep_prep?.hints?.filter(Boolean).length > 0 && (
        <div className="space-y-1">
          {data.sleep_prep.hints.filter(Boolean).map((h, i) => (
            <div key={i} className="text-[13px] text-purple-300/60">{h}</div>
          ))}
        </div>
      )}

      {/* Journal prompt */}
      {data?.journal_prompt && (
        <div className="flex items-start gap-2 mt-4 bg-purple-500/5 rounded-xl px-5 py-3 border border-purple-500/10">
          <BookOpen size={14} className="text-purple-400 shrink-0 mt-0.5" />
          <p className="text-sm text-purple-200/80 italic text-left">
            {data.journal_prompt}
          </p>
        </div>
      )}
    </div>
  );
}
