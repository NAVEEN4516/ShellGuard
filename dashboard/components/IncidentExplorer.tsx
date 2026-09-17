"use client";

import React, { useState } from "react";
import { BookOpen, Search, Plus, AlertCircle, ArrowUpRight, CheckCircle2 } from "lucide-react";

export interface Incident {
  id: string;
  title: string;
  severity: string;
  trigger_command: string;
  blast_radius?: string;
  safe_alternative_cmd?: string;
}

interface IncidentExplorerProps {
  incidents: Incident[];
  onSelectCommand?: (cmd: string) => void;
  onIngestIncident?: (markdown: string) => Promise<any>;
}

export default function IncidentExplorer({
  incidents,
  onSelectCommand,
  onIngestIncident,
}: IncidentExplorerProps) {
  const [searchTerm, setSearchTerm] = useState("");
  const [showIngestModal, setShowIngestModal] = useState(false);
  const [markdownInput, setMarkdownInput] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [ingestSuccess, setIngestSuccess] = useState<string | null>(null);

  const filtered = incidents.filter(
    (inc) =>
      inc.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      inc.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      inc.trigger_command.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleIngest = async () => {
    if (!markdownInput.trim() || !onIngestIncident) return;
    setIsSubmitting(true);
    try {
      const res = await onIngestIncident(markdownInput);
      setIngestSuccess(`Successfully learned ${res.incident_id || "new incident"}! Total chunks: ${res.total_docs || ""}`);
      setMarkdownInput("");
      setTimeout(() => {
        setIngestSuccess(null);
        setShowIngestModal(false);
      }, 2000);
    } catch (e: any) {
      alert("Failed to ingest incident: " + e.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="bg-[#131d35]/70 border border-[#1e293b] rounded-2xl p-6 backdrop-blur-sm shadow-xl flex flex-col h-[520px]">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4 pb-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-[#06b6d4]" />
          <h2 className="text-base font-bold text-white tracking-wide">
            Enterprise Disaster Post-Mortems
          </h2>
          <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
            {incidents.length} loaded
          </span>
        </div>

        <button
          onClick={() => setShowIngestModal(true)}
          className="flex items-center gap-1.5 px-3 py-1 bg-purple-600/20 hover:bg-purple-600/30 text-purple-300 border border-purple-500/40 rounded-lg text-xs font-mono font-semibold transition-all"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Learn New Incident</span>
        </button>
      </div>

      {/* Search Bar */}
      <div className="relative mb-3">
        <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
        <input
          type="text"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Search post-mortems (e.g. ingress, terraform, S3, INC-402)..."
          className="w-full bg-[#090d16] border border-slate-700 rounded-xl pl-9 pr-4 py-2 text-xs font-mono text-white placeholder-slate-500 focus:outline-none focus:border-[#06b6d4]"
        />
      </div>

      {/* Incidents Grid/List */}
      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {filtered.map((inc) => (
          <div
            key={inc.id}
            className="p-4 rounded-xl bg-slate-900/40 border border-slate-800 hover:border-slate-700 transition-all flex flex-col justify-between"
          >
            <div>
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono font-bold text-white bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
                    {inc.id}
                  </span>
                  <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/40">
                    {inc.severity}
                  </span>
                </div>

                {onSelectCommand && (
                  <button
                    onClick={() => onSelectCommand(inc.trigger_command)}
                    className="flex items-center gap-1 text-[11px] font-mono text-[#06b6d4] hover:text-sky-300 transition-colors"
                  >
                    <span>Test Command</span>
                    <ArrowUpRight className="w-3 h-3" />
                  </button>
                )}
              </div>

              <h3 className="text-xs font-bold text-white mb-1.5">{inc.title}</h3>

              <div className="text-[11px] font-mono text-slate-400 bg-[#090d16] p-2 rounded border border-slate-800/80 mb-2 truncate">
                <span className="text-slate-500">$ </span>
                <span className="text-rose-300">{inc.trigger_command}</span>
              </div>

              {inc.blast_radius && (
                <div className="text-[11px] font-mono text-slate-400 line-clamp-2">
                  <strong className="text-slate-300">Blast Radius:</strong> {inc.blast_radius}
                </div>
              )}
            </div>

            {inc.safe_alternative_cmd && (
              <div className="mt-2 pt-2 border-t border-slate-800/60 text-[11px] font-mono text-emerald-400 truncate">
                <strong className="text-emerald-300">Alternative:</strong> {inc.safe_alternative_cmd}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Dynamic Ingest Modal */}
      {showIngestModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#131d35] border border-slate-700 rounded-2xl max-w-xl w-full p-6 shadow-2xl">
            <h3 className="text-base font-bold text-white mb-2 flex items-center gap-2">
              <Plus className="w-5 h-5 text-purple-400" />
              Dynamic Incident Learning (Hot-Reload)
            </h3>
            <p className="text-xs text-slate-400 font-mono mb-4">
              Paste disaster post-mortem markdown to ingest directly into in-memory Moss runtime without daemon restarts.
            </p>

            <textarea
              rows={8}
              value={markdownInput}
              onChange={(e) => setMarkdownInput(e.target.value)}
              placeholder={`# INC-999: Production Database Flush\n\n## 1. Triggering Command\n\`\`\`bash\nredis-cli flushall --async\n\`\`\`\n\n## 2. Blast Radius\nComplete loss of cached sessions.\n\n## 3. Mandatory Safe Alternative\n\`\`\`bash\nredis-cli ping\n\`\`\``}
              className="w-full bg-[#090d16] border border-slate-700 rounded-xl p-3 text-xs font-mono text-white placeholder-slate-600 focus:outline-none focus:border-purple-400 mb-4"
            />

            {ingestSuccess && (
              <div className="p-3 mb-4 rounded-xl bg-emerald-950/40 border border-emerald-500/40 text-emerald-300 text-xs font-mono flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>{ingestSuccess}</span>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowIngestModal(false)}
                className="px-4 py-2 rounded-xl text-xs font-mono text-slate-400 hover:text-white bg-slate-900 border border-slate-800"
              >
                Cancel
              </button>
              <button
                onClick={handleIngest}
                disabled={isSubmitting || !markdownInput.trim()}
                className="px-4 py-2 rounded-xl text-xs font-mono font-bold bg-purple-600 hover:bg-purple-500 text-white transition-all disabled:opacity-50"
              >
                {isSubmitting ? "Ingesting..." : "Learn Incident"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
