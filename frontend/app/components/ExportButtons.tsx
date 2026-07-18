"use client";

import { useState } from "react";
import { ExportFormat, exportUrl } from "../lib/api";

const EXPORTS: { format: ExportFormat; label: string; note: string; ext: string }[] = [
  {
    format: "ucp_supplemental",
    label: "UCP Supplemental Feed",
    note: "Google Merchant Center",
    ext: "json",
  },
  {
    format: "acp_feed",
    label: "ACP Product Feed",
    note: "ChatGPT discovery",
    ext: "jsonl",
  },
  {
    format: "asa_readiness",
    label: "ASA Readiness Report",
    note: "Amazon readiness summary",
    ext: "json",
  },
  {
    format: "enriched_csv",
    label: "Enriched CSV",
    note: "Full catalog export",
    ext: "csv",
  },
];

export default function ExportButtons({
  sessionId,
  enabled,
}: {
  sessionId: string;
  enabled: boolean;
}) {
  const [status, setStatus] = useState<Record<string, string>>({});

  async function download(format: ExportFormat, ext: string) {
    setStatus((s) => ({ ...s, [format]: "loading" }));
    try {
      const res = await fetch(exportUrl(sessionId, format));
      if (!res.ok) {
        setStatus((s) => ({ ...s, [format]: `Export failed (${res.status}).` }));
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${format}-${sessionId}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
      setStatus((s) => ({ ...s, [format]: "" }));
    } catch {
      setStatus((s) => ({ ...s, [format]: "Export failed." }));
    }
  }

  return (
    <section className={`card${enabled ? "" : " disabled"}`}>
      <h2>
        <span className="step-badge">5</span> Exports
      </h2>
      <div className="export-row">
        {EXPORTS.map((exp) => (
          <div className="export-btn-wrap" key={exp.format}>
            <button
              onClick={() => download(exp.format, exp.ext)}
              disabled={!enabled || status[exp.format] === "loading"}
            >
              {status[exp.format] === "loading" ? "Preparing…" : exp.label}
            </button>
            <span className="export-note">
              {status[exp.format] && status[exp.format] !== "loading"
                ? status[exp.format]
                : exp.note}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
