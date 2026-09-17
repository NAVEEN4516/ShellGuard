"use client";

import React, { useState, useEffect } from "react";
import { Volume2, VolumeX, Users, Radio, AlertTriangle, Play, ShieldAlert } from "lucide-react";

interface LiveKitWarRoomProps {
  latestAlert?: {
    incident_id: string;
    title: string;
    command: string;
    room_name: string;
    token: string;
    severity?: string;
  } | null;
  onDispatchAlert?: (incidentId: string) => Promise<any>;
}

export default function LiveKitWarRoom({
  latestAlert,
  onDispatchAlert,
}: LiveKitWarRoomProps) {
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [inWarRoom, setInWarRoom] = useState(false);
  const [isPlayingChime, setIsPlayingChime] = useState(false);
  const [activeRoom, setActiveRoom] = useState<string>("shellguard-ops-lobby");
  const [activeToken, setActiveToken] = useState<string>("");

  useEffect(() => {
    if (latestAlert) {
      setActiveRoom(latestAlert.room_name);
      setActiveToken(latestAlert.token);
      if (audioEnabled) {
        playEmergencyChime();
      }
    }
  }, [latestAlert]);

  const playEmergencyChime = () => {
    if (typeof window === "undefined") return;
    try {
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioContextClass) return;
      const ctx = new AudioContextClass();
      setIsPlayingChime(true);

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = "sine";
      osc.frequency.setValueAtTime(880, ctx.currentTime); // High-A chime
      osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.3);

      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.35);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start();
      osc.stop(ctx.currentTime + 0.35);

      setTimeout(() => {
        setIsPlayingChime(false);
      }, 400);
    } catch (e) {
      console.warn("Audio chime playback error:", e);
      setIsPlayingChime(false);
    }
  };

  const handleToggleWarRoom = () => {
    setInWarRoom(!inWarRoom);
  };

  return (
    <div className="bg-[#131d35]/70 border border-[#1e293b] rounded-2xl p-6 backdrop-blur-sm shadow-xl flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Radio className={`w-5 h-5 ${inWarRoom ? "text-rose-400 animate-pulse" : "text-[#8b5cf6]"}`} />
            <h2 className="text-base font-bold text-white tracking-wide">
              LiveKit WebRTC SRE War Room
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={playEmergencyChime}
              disabled={isPlayingChime}
              title="Test LiveKit Audio Chime"
              className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
            >
              <Volume2 className={`w-4 h-4 ${isPlayingChime ? "text-amber-400" : ""}`} />
            </button>
            <button
              onClick={() => setAudioEnabled(!audioEnabled)}
              title={audioEnabled ? "Disable Alert Chimes" : "Enable Alert Chimes"}
              className={`p-1.5 rounded-lg border transition-colors ${
                audioEnabled
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                  : "bg-slate-800 text-slate-500 border-slate-700"
              }`}
            >
              {audioEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
            </button>
          </div>
        </div>

        <p className="text-xs text-slate-400 mb-4 font-mono">
          Real-time WebRTC audio alerts and incident collaboration rooms triggered instantly upon terminal command interception.
        </p>

        {/* Status card */}
        <div className={`p-4 rounded-xl border mb-4 transition-all ${
          latestAlert
            ? "bg-rose-950/30 border-rose-500/40 text-rose-200"
            : "bg-[#090d16]/80 border-slate-800 text-slate-300"
        }`}>
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              {latestAlert ? (
                <ShieldAlert className="w-5 h-5 text-rose-400 shrink-0" />
              ) : (
                <Users className="w-5 h-5 text-purple-400 shrink-0" />
              )}
              <div>
                <div className="text-xs font-mono font-bold">
                  {latestAlert ? `EMERGENCY ALERT: ${latestAlert.incident_id}` : "WAR ROOM STANDBY"}
                </div>
                <div className="text-[11px] text-slate-400 font-mono">
                  {latestAlert ? latestAlert.title : "Active bridge ready for high-risk interventions"}
                </div>
              </div>
            </div>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-purple-900/50 text-purple-300 border border-purple-500/30">
              WebRTC
            </span>
          </div>

          <div className="mt-3 pt-3 border-t border-slate-800/80 flex flex-wrap items-center justify-between text-xs font-mono gap-2">
            <span className="text-slate-400">Room: <span className="text-white font-bold">{activeRoom}</span></span>
            <span className="text-slate-400">Audio Chime: <span className={audioEnabled ? "text-emerald-400 font-bold" : "text-slate-500"}>{audioEnabled ? "ACTIVE (880Hz)" : "MUTED"}</span></span>
          </div>
        </div>
      </div>

      <div className="pt-2">
        <button
          onClick={handleToggleWarRoom}
          className={`w-full py-2.5 px-4 rounded-xl font-mono text-xs font-bold flex items-center justify-center gap-2 transition-all shadow-lg ${
            inWarRoom
              ? "bg-rose-600 hover:bg-rose-500 text-white shadow-rose-600/30"
              : "bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white shadow-purple-600/20"
          }`}
        >
          <Radio className="w-4 h-4" />
          <span>{inWarRoom ? "Disconnect SRE War Room" : "Connect LiveKit WebRTC Session"}</span>
        </button>
      </div>
    </div>
  );
}
