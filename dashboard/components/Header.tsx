"use client";

import React from "react";
import { Shield, Radio, Activity, Lock, Cpu } from "lucide-react";

interface HeaderProps {
  p50Latency?: number;
  totalChecks?: number;
  blockedCount?: number;
  envBadge?: string;
  isOnline?: boolean;
}

export default function Header({
  p50Latency = 3.7,
  totalChecks = 0,
  blockedCount = 0,
  envBadge = "[ENV: prod-us-east-1 (k8s)]",
  isOnline = true,
}: HeaderProps) {
  return (
    <header className="bg-[#0f172a]/90 backdrop-blur-md border-b border-[#1e293b] px-6 py-4 sticky top-0 z-50 flex flex-wrap justify-between items-center gap-4">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-[#06b6d4] to-[#3b82f6] flex items-center justify-center text-white shadow-lg shadow-[#06b6d4]/20">
          <Shield className="w-6 h-6" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-100 to-sky-300 bg-clip-text text-transparent">
              ShellGuard
            </h1>
            <span className="text-[10px] font-mono font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-[#06b6d4]/10 text-[#06b6d4] border border-[#06b6d4]/30">
              Next.js Cockpit
            </span>
            <span className="text-[10px] font-mono font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-[#10b981]/10 text-[#10b981] border border-[#10b981]/30">
              Moss In-Process
            </span>
            <span className="text-[10px] font-mono font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-[#8b5cf6]/10 text-[#8b5cf6] border border-[#8b5cf6]/30">
              LiveKit WebRTC
            </span>
          </div>
          <p className="text-xs text-slate-400 font-mono flex items-center gap-2">
            <span>Zero-Latency Terminal Interceptor</span>
            <span className="text-slate-600">•</span>
            <span className="text-emerald-400 flex items-center gap-1">
              <Lock className="w-3 h-3 inline" /> OWASP Hardened
            </span>
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {envBadge && (
          <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/80 border border-slate-700 text-xs font-mono text-purple-300">
            <Cpu className="w-3.5 h-3.5 text-purple-400" />
            <span>{envBadge}</span>
          </div>
        )}

        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/80 border border-slate-700 text-xs font-mono">
          <span className="text-slate-400">p50 Latency:</span>
          <span className="font-bold text-[#06b6d4]">{p50Latency.toFixed(1)}ms</span>
        </div>

        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/80 border border-slate-700 text-xs font-mono">
          <span className="text-slate-400">Interceptions:</span>
          <span className="font-bold text-rose-400">{blockedCount}</span>
          <span className="text-slate-600">/</span>
          <span className="text-slate-300">{totalChecks}</span>
        </div>

        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/80 border border-slate-700 text-xs font-mono">
          <span className={`w-2 h-2 rounded-full ${isOnline ? "bg-emerald-400 animate-pulse" : "bg-rose-500"}`} />
          <span className="text-slate-200">{isOnline ? "DAEMON LIVE" : "OFFLINE"}</span>
        </div>
      </div>
    </header>
  );
}
