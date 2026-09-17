"use client";

import React, { useState } from "react";
import { Play, Copy, Check, ShieldAlert, ShieldCheck, AlertTriangle, Terminal, Zap } from "lucide-react";

interface CommandSimulatorProps {
  onEvaluate: (command: string) => Promise<any>;
  activeCommand?: string;
}

export default function CommandSimulator({
  onEvaluate,
  activeCommand = "kubectl delete namespace ingress-nginx",
}: CommandSimulatorProps) {
  const [command, setCommand] = useState(activeCommand);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [copied, setCopied] = useState(false);

  // Sync if parent updates command
  React.useEffect(() => {
    if (activeCommand) {
      setCommand(activeCommand);
    }
  }, [activeCommand]);

  const handleRun = async (cmdToRun?: string) => {
    const target = cmdToRun || command;
    if (!target.trim()) return;
    setIsLoading(true);
    try {
      const res = await onEvaluate(target);
      setResult(res);
    } finally {
      setIsLoading(false);
    }
  };

  const copySafeCommand = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const presets = [
    { label: "k8s delete ns (INC-402)", cmd: "kubectl delete namespace ingress-nginx", type: "danger" },
    { label: "s3 recursive rm (INC-109)", cmd: "aws s3 rm s3://company-prod-backups --recursive", type: "danger" },
    { label: "tf destroy rds (INC-105)", cmd: "terraform destroy -target=aws_db_instance.primary", type: "danger" },
    { label: "git push --force (INC-770)", cmd: "git push --force origin main", type: "danger" },
    { label: "rm -rf / (INC-204)", cmd: "sudo rm -rf /", type: "danger" },
    { label: "k8s get pods (Safe)", cmd: "kubectl get pods -n kube-system", type: "safe" },
    { label: "tf plan (Safe)", cmd: "terraform plan", type: "safe" },
    { label: "aws s3 ls (Safe)", cmd: "aws s3 ls", type: "safe" },
  ];

  return (
    <div className="bg-[#131d35]/70 border border-[#1e293b] rounded-2xl p-6 backdrop-blur-sm shadow-xl flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Terminal className="w-5 h-5 text-[#06b6d4]" />
            <h2 className="text-base font-bold text-white tracking-wide">
              Zero-Latency Interception Simulator
            </h2>
          </div>
          <span className="text-xs font-mono text-slate-400">
            Target SLA: &lt;10ms
          </span>
        </div>

        {/* Input box */}
        <div className="relative mb-3">
          <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500 font-mono text-sm">
            $
          </div>
          <input
            type="text"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleRun()}
            placeholder="Type terminal command (e.g. kubectl delete namespace ingress-nginx)..."
            className="w-full bg-[#090d16] border border-slate-700 rounded-xl pl-8 pr-28 py-3 text-sm font-mono text-white placeholder-slate-500 focus:outline-none focus:border-[#06b6d4] focus:ring-1 focus:ring-[#06b6d4]"
          />
          <button
            onClick={() => handleRun()}
            disabled={isLoading || !command.trim()}
            className="absolute right-2 top-2 bottom-2 px-4 bg-gradient-to-r from-[#06b6d4] to-[#3b82f6] hover:from-[#22d3ee] hover:to-[#60a5fa] text-slate-950 font-bold font-mono text-xs rounded-lg flex items-center gap-1.5 transition-all disabled:opacity-50"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>{isLoading ? "Checking..." : "Intercept"}</span>
          </button>
        </div>

        {/* Presets */}
        <div className="mb-6">
          <div className="text-[11px] font-mono text-slate-400 mb-2">Preset Test Commands:</div>
          <div className="flex flex-wrap gap-1.5">
            {presets.map((p, idx) => (
              <button
                key={idx}
                onClick={() => {
                  setCommand(p.cmd);
                  handleRun(p.cmd);
                }}
                className={`text-[11px] font-mono px-2.5 py-1 rounded-md border transition-all ${
                  p.type === "danger"
                    ? "bg-rose-950/20 text-rose-300 border-rose-900/40 hover:bg-rose-900/30 hover:border-rose-700"
                    : "bg-emerald-950/20 text-emerald-300 border-emerald-900/40 hover:bg-emerald-900/30 hover:border-emerald-700"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Result Panel */}
        {result && (
          <div
            className={`p-4 rounded-xl border transition-all ${
              result.status === "BLOCKED"
                ? "bg-rose-950/30 border-rose-600/50"
                : result.status === "WARNING"
                ? "bg-amber-950/30 border-amber-600/50"
                : "bg-emerald-950/30 border-emerald-600/50"
            }`}
          >
            <div className="flex items-start justify-between gap-3 mb-2">
              <div className="flex items-center gap-2">
                {result.status === "BLOCKED" && (
                  <span className="flex items-center gap-1.5 font-mono text-xs font-bold px-2.5 py-1 rounded-md bg-rose-500 text-white">
                    <ShieldAlert className="w-4 h-4" /> EXECUTION PREVENTED
                  </span>
                )}
                {result.status === "WARNING" && (
                  <span className="flex items-center gap-1.5 font-mono text-xs font-bold px-2.5 py-1 rounded-md bg-amber-500 text-slate-950">
                    <AlertTriangle className="w-4 h-4" /> HIGH RISK WARNING
                  </span>
                )}
                {result.status === "PASSED" && (
                  <span className="flex items-center gap-1.5 font-mono text-xs font-bold px-2.5 py-1 rounded-md bg-emerald-500 text-slate-950">
                    <ShieldCheck className="w-4 h-4" /> VERIFIED SAFE TO EXECUTE
                  </span>
                )}

                {result.env_badge && (
                  <span className="text-xs font-mono px-2 py-0.5 rounded bg-purple-900/50 text-purple-300 border border-purple-700">
                    {result.env_badge}
                  </span>
                )}
              </div>

              <div className="flex items-center gap-1 text-xs font-mono text-[#06b6d4] font-bold bg-slate-900/80 px-2.5 py-1 rounded-md border border-slate-700">
                <Zap className="w-3.5 h-3.5" />
                <span>{(result.total_api_latency_ms || result.latency_ms || 3.7).toFixed(2)} ms</span>
              </div>
            </div>

            {/* Matched Incident Details */}
            {result.matched_incident_id && (
              <div className="mt-3 text-xs font-mono space-y-2">
                <div className="text-slate-300">
                  <span className="text-slate-400">Incident: </span>
                  <strong className="text-white">{result.matched_incident_id}</strong> — {result.matched_incident_title}
                  {result.similarity_score && (
                    <span className="text-amber-400 ml-2">({(result.similarity_score * 100).toFixed(1)}% match)</span>
                  )}
                </div>

                {result.blast_radius && (
                  <div className="text-rose-300 text-[11px] bg-rose-950/40 p-2.5 rounded-lg border border-rose-800/30">
                    <strong className="text-rose-400">Blast Radius: </strong> {result.blast_radius}
                  </div>
                )}

                {(result.safe_alternative_cmd || result.safe_alternative) && (
                  <div className="mt-2 bg-[#090d16] p-3 rounded-lg border border-emerald-500/30 flex items-center justify-between gap-2">
                    <div className="text-emerald-300 font-mono text-xs truncate">
                      <span className="text-emerald-400 font-bold block text-[10px] uppercase">Safe Alternative:</span>
                      {result.safe_alternative_cmd || result.safe_alternative}
                    </div>
                    <button
                      onClick={() => copySafeCommand(result.safe_alternative_cmd || result.safe_alternative)}
                      className="p-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 transition-colors shrink-0"
                      title="Copy Safe Command"
                    >
                      {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="text-[11px] font-mono text-slate-500 mt-4 flex items-center justify-between border-t border-slate-800/80 pt-3">
        <span>Evaluator: Moss In-Process Runtime</span>
        <span className="text-emerald-400">Zero Network Hops</span>
      </div>
    </div>
  );
}
