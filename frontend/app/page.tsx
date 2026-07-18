"use client";

import { useState } from "react";
import {
  EnrichResponse,
  StartResponse,
  confirmEnrich,
  confirmValidate,
  startPipeline,
} from "./lib/api";
import UploadZone from "./components/UploadZone";
import AuditResults from "./components/AuditResults";
import EnrichmentResults from "./components/EnrichmentResults";
import ValidationChat from "./components/ValidationChat";
import ExportButtons from "./components/ExportButtons";

export default function Home() {
  const [fileName, setFileName] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [audit, setAudit] = useState<StartResponse | null>(null);

  const [enriching, setEnriching] = useState(false);
  const [enrichError, setEnrichError] = useState<string | null>(null);
  const [enrichment, setEnrichment] = useState<EnrichResponse | null>(null);

  const [confirmingValidate, setConfirmingValidate] = useState(false);
  const [validateError, setValidateError] = useState<string | null>(null);
  const [validateEnabled, setValidateEnabled] = useState(false);

  async function handleFile(file: File) {
    setUploading(true);
    setUploadError(null);
    setAudit(null);
    setEnrichment(null);
    setValidateEnabled(false);
    try {
      const result = await startPipeline(file);
      setFileName(file.name);
      setAudit(result);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleConfirmEnrich() {
    if (!audit) return;
    setEnriching(true);
    setEnrichError(null);
    try {
      const result = await confirmEnrich(audit.session_id);
      setEnrichment(result);
    } catch (err) {
      setEnrichError(err instanceof Error ? err.message : "Enrichment failed");
    } finally {
      setEnriching(false);
    }
  }

  async function handleConfirmValidate() {
    if (!audit) return;
    setConfirmingValidate(true);
    setValidateError(null);
    try {
      await confirmValidate(audit.session_id);
      setValidateEnabled(true);
    } catch (err) {
      setValidateError(
        err instanceof Error ? err.message : "Could not enable validation"
      );
    } finally {
      setConfirmingValidate(false);
    }
  }

  return (
    <main>
      <div>
        <h1>RIA v2</h1>
        <p className="subtitle">
          Upload a catalog, audit its agent-readiness, enrich the gaps, then
          watch a shopping agent resolve a query against the raw catalog vs.
          the enriched one.
        </p>
      </div>

      <UploadZone
        onFile={handleFile}
        uploading={uploading}
        error={uploadError}
        fileName={fileName}
      />

      {audit && (
        <AuditResults
          data={audit}
          onConfirmEnrich={handleConfirmEnrich}
          enriching={enriching}
          error={enrichError}
          alreadyEnriched={!!enrichment}
        />
      )}

      {enrichment && (
        <EnrichmentResults
          data={enrichment}
          onConfirmValidate={handleConfirmValidate}
          confirming={confirmingValidate}
          error={validateError}
          validateEnabled={validateEnabled}
        />
      )}

      {audit && (
        <ValidationChat sessionId={audit.session_id} enabled={validateEnabled} />
      )}

      {audit && (
        <ExportButtons sessionId={audit.session_id} enabled={validateEnabled} />
      )}
    </main>
  );
}
