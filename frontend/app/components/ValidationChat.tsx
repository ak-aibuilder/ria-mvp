"use client";

import { useState } from "react";
import { AgentTranscript, CompareResponse, compareQuery } from "../lib/api";

function AgentColumn({
  label,
  transcript,
  betterProducts,
  betterCalls,
}: {
  label: string;
  transcript: AgentTranscript;
  betterProducts: boolean;
  betterCalls: boolean;
}) {
  return (
    <div className="agent-col">
      <h4>
        <span>{label}</span>
      </h4>
      <div className="agent-response">{transcript.agent_response}</div>
      <div className="agent-stats">
        <span className={betterProducts ? "better" : undefined}>
          {transcript.skus_examined.length} products examined
        </span>
        <span className={betterCalls ? "better" : undefined}>
          {transcript.tool_call_count} tool calls
        </span>
        <span>{transcript.turns_used} turns</span>
      </div>
      {transcript.skus_examined.length > 0 && (
        <div className="sku-list">{transcript.skus_examined.join(", ")}</div>
      )}
      {transcript.fallback_fired && (
        <p className="error-text" style={{ fontSize: "0.75rem" }}>
          Text-based tool-call fallback fired for this turn.
        </p>
      )}
      {transcript.checkout_intent && (
        <span className="checkout-badge">
          ✓ Checkout intent generated ({String(transcript.checkout_intent.intent_version)})
        </span>
      )}
    </div>
  );
}

function CompareCard({ result }: { result: CompareResponse }) {
  const preProducts = result.pre.skus_examined.length;
  const postProducts = result.post.skus_examined.length;
  const preCalls = result.pre.tool_call_count;
  const postCalls = result.post.tool_call_count;

  return (
    <div className="compare-card">
      <div className="compare-query">"{result.query}"</div>
      <div className="agent-stats">
        <span>
          Tokens — pre {result.query_comparison.pre.total_tokens} / post{" "}
          {result.query_comparison.post.total_tokens} (
          {result.query_comparison.token_reduction_pct >= 0 ? "-" : "+"}
          {Math.abs(result.query_comparison.token_reduction_pct)}%, supporting
          data point only — see Eval 4)
        </span>
      </div>
      <div className="compare-cols">
        <AgentColumn
          label="Pre-enrichment"
          transcript={result.pre}
          betterProducts={preProducts < postProducts}
          betterCalls={preCalls < postCalls}
        />
        <AgentColumn
          label="Post-enrichment"
          transcript={result.post}
          betterProducts={postProducts < preProducts}
          betterCalls={postCalls < preCalls}
        />
      </div>
    </div>
  );
}

export default function ValidationChat({
  sessionId,
  enabled,
}: {
  sessionId: string;
  enabled: boolean;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CompareResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      const result = await compareQuery(sessionId, query.trim());
      setResults((prev) => [...prev, result]);
      setQuery("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className={`card${enabled ? "" : " disabled"}`}>
      <h2>
        <span className="step-badge">4</span> Validation Chat
      </h2>
      <p className="subtitle">
        Run the same query against the pre- and post-enrichment agent (goals.md
        §4 Eval 4 — fewer products examined and fewer-or-equal tool calls wins).
      </p>
      <form className="chat-form" onSubmit={submit}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='e.g. "waterproof jacket under $200 in size M"'
          disabled={!enabled || loading}
        />
        <button className="primary" type="submit" disabled={!enabled || loading}>
          {loading ? "Running…" : "Ask"}
        </button>
      </form>
      {error && <p className="error-text">{error}</p>}
      {results.map((r, i) => (
        <CompareCard key={i} result={r} />
      ))}
    </section>
  );
}
