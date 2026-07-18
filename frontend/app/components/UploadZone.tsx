"use client";

import { useRef, useState } from "react";

export default function UploadZone({
  onFile,
  uploading,
  error,
  fileName,
}: {
  onFile: (file: File) => void;
  uploading: boolean;
  error: string | null;
  fileName: string | null;
}) {
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) onFile(file);
  }

  return (
    <section className="card">
      <h2>
        <span className="step-badge">1</span> Upload Catalog CSV
      </h2>
      <div
        className={`dropzone${dragActive ? " active" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
      >
        {uploading ? (
          <p>Uploading and auditing…</p>
        ) : fileName ? (
          <p>
            Loaded <strong>{fileName}</strong>.{" "}
            <label onClick={() => inputRef.current?.click()}>
              Upload a different file
            </label>
          </p>
        ) : (
          <p>
            Drag a Shopify-format product CSV here, or{" "}
            <label onClick={() => inputRef.current?.click()}>browse</label>.
          </p>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".csv"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onFile(file);
          }}
        />
      </div>
      {error && <p className="error-text">{error}</p>}
    </section>
  );
}
