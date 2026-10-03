"use client";

// Tiny markdown renderer: headings, bullets, bold, italics. Builds React
// elements (no innerHTML), so model output can never inject HTML.
function inline(text, key) {
  return text.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).filter(Boolean).map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={`${key}-${i}`}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("_") && p.endsWith("_") && p.length > 2) return <em key={`${key}-${i}`}>{p.slice(1, -1)}</em>;
    return p;
  });
}

export function Markdown({ text }) {
  const out = [];
  let list = [];
  const flush = () => {
    if (list.length) out.push(<ul key={`ul${out.length}`}>{list}</ul>);
    list = [];
  };
  (text || "").split("\n").forEach((raw, i) => {
    const line = raw.trim();
    if (!line) { flush(); return; }
    const bullet = line.match(/^[-*•]\s+(.*)/);
    if (bullet) { list.push(<li key={i}>{inline(bullet[1], i)}</li>); return; }
    flush();
    const heading = line.match(/^#{1,6}\s+(.*)/) || line.match(/^(\d+\.\s+.*)$/);
    if (heading) out.push(<h4 key={i}>{inline(heading[1].replace(/\*\*/g, ""), i)}</h4>);
    else out.push(<p key={i}>{inline(line, i)}</p>);
  });
  flush();
  return <div className="report-body">{out}</div>;
}

const ENGINE = { claude: "Claude", gemini: "Gemini", template: "Offline template" };
export const engineLabel = (r) => (r.engine === "template" ? ENGINE.template : `${ENGINE[r.engine] || r.engine} · ${r.model}`);

export function DownloadLinks({ id }) {
  if (!id) return null;
  const base = `/api/reports/${id}/download`;
  return (
    <span className="row" style={{ gap: 8 }}>
      <a className="btn small" href={`${base}?format=html&inline=1`} target="_blank" rel="noreferrer">PDF / Print</a>
      <a className="btn small" href={`${base}?format=txt`} download>TXT</a>
      <a className="btn small" href={`${base}?format=md`} download>MD</a>
    </span>
  );
}
