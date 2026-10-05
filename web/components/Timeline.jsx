"use client";
import { ago, clock } from "@/lib/api";
import { useLive } from "@/lib/live";

/** Pause / rewind bar. Live by default; drag, click a chart, or use ← → to inspect a past reading. */
export default function Timeline() {
  const { frames, cursor, live, pause, goLive, inspect, latest } = useLive();
  if (!frames.length) return null;

  const foundIdx = cursor == null ? -1 : frames.findIndex((f) => f.ts === cursor);
  const idx = live ? frames.length - 1 : (foundIdx >= 0 ? foundIdx : 0);
  const shown = frames[idx];
  const step = (d) => {
    const j = Math.min(frames.length - 1, Math.max(0, idx + d));
    inspect(frames[j].ts);
  };
  const behind = latest && shown ? latest.ts - shown.ts : 0;

  return (
    <section className={`card timeline ${live ? "" : "paused"}`} aria-label="Timeline">
      <div className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
        {live ? (
          <button className="btn" onClick={pause} title="Pause (Space)">❚❚ Pause</button>
        ) : (
          <button className="btn primary" onClick={goLive} title="Back to live (L)">● Go live</button>
        )}
        <button className="btn small" onClick={() => step(-1)} disabled={idx === 0} aria-label="Previous reading (←)">◀</button>
        <button className="btn small" onClick={() => step(1)} disabled={live} aria-label="Next reading (→)">▶</button>
        <div className="track">
          <div className="marks" aria-hidden="true">
            {frames.map((f, i) => f.alert ? (
              <span key={f.ts} className="mark" style={{ left: `${(i / Math.max(1, frames.length - 1)) * 100}%` }} />
            ) : null)}
          </div>
          <input type="range" min={0} max={frames.length - 1} value={idx}
            onChange={(e) => {
              const j = Number(e.target.value);
              if (j === frames.length - 1) goLive(); else inspect(frames[j].ts);
            }}
            aria-label="Scrub through recent readings" />
        </div>
        <span className="timeline-label num">
          {live ? <><span className="live-dot" aria-hidden="true" /> Live</> : <>{clock(shown.ts)} · {ago(behind)}</>}
        </span>
      </div>
      {!live && (
        <div className="hint">
          Paused on a past reading. Every panel shows that moment. New data keeps buffering, so nothing is lost.
          Red ticks mark alerts.
        </div>
      )}
    </section>
  );
}
