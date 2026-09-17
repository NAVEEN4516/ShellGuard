"use client";

import React, { useState } from "react";
import { ShieldCheck, ShieldAlert, AlertTriangle, Terminal, Filter, ArrowUpRight, Copy, Check } from "lucide-react";

export interface InterceptionItem {
  id: string;
  command: string;
  status: "BLOCKED" | "WARNING" | "PASSED";
  matched_incident_id?: string;
  matched_incident_title?: string;
  similarity_score?: number;
  latency_ms: number;
  blast_radius?: string;
  safe_alternative_cmd?: string;
  env_badge?: string;
  timestamp: string;
}

interface RadarFeedProps {
  items: InterceptionItem[];
  onSelectCommand?: (cmd: string) => void;
}

export default function RadarFeed({ items, onSelectCommand }: RadarFeedProps) {
  const [filter, setFilter] = useState<"ALL" | "BLOCKED" | "WARNING" | "PASSED">("ALL");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const filteredItems = items.filter((item) => {
    if (filter === "ALL") return true;
    return item.status === filter;
  });

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  return (
    <div className="bg-[#131d35]/70 border border-[#1e293b] rounded-2xl p-6 backdrop-blur-sm shadow-xl flex flex-col h-[520px]">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4 pb-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Terminal className="w-5 h-5 text-[#06b6d4]" />
          <h2 className="text-base font-bold text-white tracking-wide">
            Live Command Interception Radar
          </h2>
          <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
            {filteredItems.length}
          </span>
        </div>

        {/* Filter chips */}
        <div className="flex items-center gap-1.5 text-xs font-mono">
          {(["ALL", "BLOCKED", "WARNING", "PASSED"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setFilter(mode)}
              className={`px-2.5 py-1 rounded-lg transition-all ${
                filter === mode
                  ? "bg-[#06b6d4] text-slate-950 font-bold shadow-sm shadow-[#06b6d4]/30"
                  : "bg-slate-900 text-slate-400 hover:text-white hover:bg-slate-800 border border-slate-800"
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      {/* Feed list */}
      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {filteredItems.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-8 text-slate-500 font-mono text-xs">
            <Terminal className="w-8 h-8 mb-2 opacity-30" />
            <span>No command interceptions recorded yet. Run terminal commands or use the simulator.</span>
          </div>
        ) : (
          filteredItems.map((item) => (
            <div
              key={item.id}
              className={`p-4 rounded-xl border transition-all ${
                item.status === "BLOCKED"
                  ? "bg-rose-950/20 border-rose-900/50 hover:border-rose-700/60"
                  : item.status === "WARNING"
                  ? "bg-amber-950/20 border-amber-900/50 hover:border-amber-700/60"
                  : "bg-slate-900/40 border-slate-800 hover:border-slate-700"
              }`}
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex items-center gap-2">
                  {item.status === "BLOCKED" && (
                    <span className="flex items-center gap-1 text-[11px] font-mono font-bold px-2 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/40">
                      <ShieldAlert className="w-3 h-3" /> BLOCKED
                    </span>
                  )}
                  {item.status === "WARNING" && (
                    <span className="flex items-center gap-1 text-[11px] font-mono font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/40">
                      <AlertTriangle className="w-3 h-3" /> WARNING
                    </span>
                  )}
                  {item.status === "PASSED" && (
                    <span className="flex items-center gap-1 text-[11px] font-mono font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
                      <ShieldCheck className="w-3 h-3" /> PASSED
                    </span>
                  )}

                  {item.env_badge && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-purple-900/40 text-purple-300 border border-purple-800/40">
                      {item.env_badge}
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2 text-xs font-mono text-slate-400">
                  <span className="text-[#06b6d4] font-bold">{item.latency_ms.toFixed(2)}ms</span>
                  <span>{item.timestamp}</span>
                </div>
              </div>

              {/* Command row */}
              <div className="font-mono text-xs text-white bg-[#090d16] p-2.5 rounded-lg border border-slate-800/80 flex items-center justify-between gap-2">
                <span className="truncate text-slate-200">{item.command}</span>
                {onSelectCommand && (
                  <button
                    onClick={() => onSelectCommand(item.command)}
                    title="Load into simulator"
                    className="p-1 hover:text-[#06b6d4] text-slate-500 transition-colors shrink-0"
                  >
                    <ArrowUpRight className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>

              {/* Details if blocked/warned */}
              {item.matched_incident_id && (
                <div className="mt-2 text-xs font-mono space-y-1 text-slate-300">
                  <div className="flex justify-between items-center text-slate-400 text-[11px]">
                    <span>Incident: <strong className="text-white">{item.matched_incident_id}</strong> — {item.matched_incident_title}</span>
                    {item.similarity_score !== undefined && (
                      <span className="text-amber-400">Similarity: {(item.similarity_score * 100).toFixed(1)}%</span>
                    )}
                  </div>

                  {item.safe_alternative_cmd && (
                    <div className="mt-2 p-2 rounded-lg bg-emerald-950/30 border border-emerald-800/40 flex items-center justify-between gap-2">
                      <div className="text-emerald-300 text-[11px] truncate">
                        <strong className="text-emerald-400">Safe:</strong> {item.safe_alternative_cmd}
                      </div>
                      <button
                        onClick={() => copyToClipboard(item.safe_alternative_cmd!, item.id)}
                        className="p-1 rounded text-emerald-400 hover:text-emerald-200 transition-colors shrink-0"
                        title="Copy Safe Alternative"
                      >
                        {copiedId === item.id ? <Check className="w-3.5 h-3.5 text-emerald-300" /> : <Copy className="w-3.5 h-3.5" />}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
