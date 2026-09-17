"use client";

import React, { useState, useEffect } from "react";
import Header from "../components/Header";
import LatencyGauge from "../components/LatencyGauge";
import LiveKitWarRoom from "../components/LiveKitWarRoom";
import CommandSimulator from "../components/CommandSimulator";
import RadarFeed, { InterceptionItem } from "../components/RadarFeed";
import IncidentExplorer, { Incident } from "../components/IncidentExplorer";

const DAEMON_API = process.env.NEXT_PUBLIC_DAEMON_URL || "http://127.0.0.1:8080";

const FALLBACK_INCIDENTS: Incident[] = [
  {
    id: "INC-402",
    title: "Kubernetes Ingress Controller Deletion Outage",
    severity: "P0",
    trigger_command: "kubectl delete namespace ingress-nginx",
    blast_radius: "Total drop in all inbound HTTP/HTTPS traffic across 3 availability zones.",
    safe_alternative_cmd: "kubectl get namespace ingress-nginx && kubectl get pods -n ingress-nginx",
  },
  {
    id: "INC-105",
    title: "Terraform Production RDS Database Destruction",
    severity: "P0",
    trigger_command: "terraform destroy -target=aws_db_instance.primary",
    blast_radius: "Primary PostgreSQL database deleted, 45 minutes of data loss.",
    safe_alternative_cmd: "terraform plan -target=aws_db_instance.primary",
  },
  {
    id: "INC-308",
    title: "Docker System Prune Production Volume Wipeout",
    severity: "P1",
    trigger_command: "docker system prune -a --volumes",
    blast_radius: "All local Redis and PostgreSQL volumes destroyed.",
    safe_alternative_cmd: "docker system df && docker image prune -a",
  },
  {
    id: "INC-512",
    title: "AWS S3 Bucket Public ACL Data Exposure",
    severity: "P0",
    trigger_command: "aws s3api put-bucket-acl --bucket prod --acl public-read",
    blast_radius: "Sensitive customer PII bucket exposed to public internet.",
    safe_alternative_cmd: "aws s3api get-bucket-acl --bucket prod",
  },
  {
    id: "INC-770",
    title: "Git Force Push Destroyed Production Release Branch",
    severity: "P1",
    trigger_command: "git push --force origin main",
    blast_radius: "Production release branch overwritten, unmerged commits destroyed.",
    safe_alternative_cmd: "git push origin HEAD --force-with-lease",
  },
  {
    id: "INC-204",
    title: "Root Filesystem Deletion via Unbounded rm -rf",
    severity: "P0",
    trigger_command: "rm -rf /",
    blast_radius: "Complete destruction of root operating system and mounted disks.",
    safe_alternative_cmd: "rm -i <target_file>",
  },
];

const INITIAL_RADAR_ITEMS: InterceptionItem[] = [
  {
    id: "hist-1",
    command: "kubectl delete namespace ingress-nginx",
    status: "BLOCKED",
    matched_incident_id: "INC-402",
    matched_incident_title: "Kubernetes Ingress Controller Deletion Outage",
    similarity_score: 0.94,
    latency_ms: 3.72,
    blast_radius: "Total drop in all inbound HTTP/HTTPS traffic across 3 AZs.",
    safe_alternative_cmd: "kubectl get namespace ingress-nginx",
    env_badge: "[ENV: prod-us-east-1 (k8s)]",
    timestamp: "10:14:02",
  },
  {
    id: "hist-2",
    command: "kubectl get pods -n kube-system",
    status: "PASSED",
    latency_ms: 0.85,
    env_badge: "[ENV: prod-us-east-1 (k8s)]",
    timestamp: "10:13:48",
  },
  {
    id: "hist-3",
    command: "terraform apply -auto-approve",
    status: "WARNING",
    matched_incident_id: "INC-883",
    matched_incident_title: "Automated Unattended Infrastructure Teardown",
    similarity_score: 0.62,
    latency_ms: 3.41,
    env_badge: "[ENV: prod-infrastructure (aws)]",
    timestamp: "10:12:15",
  },
];

export default function Home() {
  const [isOnline, setIsOnline] = useState(true);
  const [stats, setStats] = useState({ p50_latency_ms: 3.7, total_checks: 128, blocked: 42 });
  const [incidents, setIncidents] = useState<Incident[]>(FALLBACK_INCIDENTS);
  const [radarItems, setRadarItems] = useState<InterceptionItem[]>(INITIAL_RADAR_ITEMS);
  const [activeCommand, setActiveCommand] = useState<string>("kubectl delete namespace ingress-nginx");
  const [latestAlert, setLatestAlert] = useState<any | null>(null);
  const [envBadge, setEnvBadge] = useState<string>("[ENV: prod-us-east-1 (k8s)]");

  // Fetch telemetry from daemon
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const [statsRes, incRes, histRes] = await Promise.all([
          fetch(`${DAEMON_API}/api/stats`).then((r) => r.json()).catch(() => null),
          fetch(`${DAEMON_API}/api/incidents`).then((r) => r.json()).catch(() => null),
          fetch(`${DAEMON_API}/api/history`).then((r) => r.json()).catch(() => null),
        ]);

        if (statsRes) {
          setIsOnline(true);
          setStats({
            p50_latency_ms: statsRes.p50_latency_ms || 3.7,
            total_checks: statsRes.total_checks || 0,
            blocked: statsRes.blocked || 0,
          });
        }

        if (incRes && Array.isArray(incRes) && incRes.length > 0) {
          setIncidents(incRes);
        }

        if (histRes && Array.isArray(histRes) && histRes.length > 0) {
          const mapped: InterceptionItem[] = histRes.map((h: any, i: number) => ({
            id: `hist-${i}-${Date.now()}`,
            command: h.command,
            status: h.status,
            matched_incident_id: h.matched_incident_id,
            matched_incident_title: h.matched_incident_title,
            similarity_score: h.similarity_score,
            latency_ms: h.latency_ms || 3.7,
            blast_radius: h.blast_radius,
            safe_alternative_cmd: h.safe_alternative_cmd || h.safe_alternative,
            env_badge: h.env_badge,
            timestamp: new Date().toLocaleTimeString(),
          }));
          setRadarItems(mapped);
        }
      } catch (e) {
        setIsOnline(false);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleEvaluateCommand = async (command: string) => {
    try {
      const res = await fetch(`${DAEMON_API}/api/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command, shell: "cockpit" }),
      });

      if (res.ok) {
        const data = await res.json();
        const newItem: InterceptionItem = {
          id: `eval-${Date.now()}`,
          command: data.command,
          status: data.status,
          matched_incident_id: data.matched_incident_id,
          matched_incident_title: data.matched_incident_title,
          similarity_score: data.similarity_score,
          latency_ms: data.total_api_latency_ms || data.latency_ms || 3.7,
          blast_radius: data.blast_radius,
          safe_alternative_cmd: data.safe_alternative_cmd || data.safe_alternative,
          env_badge: data.env_badge || envBadge,
          timestamp: new Date().toLocaleTimeString(),
        };

        setRadarItems((prev) => [newItem, ...prev.slice(0, 49)]);

        if (data.status === "BLOCKED" && data.livekit_alert) {
          setLatestAlert(data.livekit_alert);
        }

        if (data.env_badge) {
          setEnvBadge(data.env_badge);
        }

        setStats((prev) => ({
          ...prev,
          total_checks: prev.total_checks + 1,
          blocked: data.status === "BLOCKED" ? prev.blocked + 1 : prev.blocked,
        }));

        return data;
      }
    } catch (e) {
      console.warn("Daemon check error:", e);
    }

    // Local simulation fallback if daemon is unreachable
    const isDangerous = /delete|destroy|rm -rf|prune|force/.test(command);
    const mockRes = {
      command,
      status: isDangerous ? "BLOCKED" : "PASSED",
      matched_incident_id: isDangerous ? "INC-402" : undefined,
      matched_incident_title: isDangerous ? "Kubernetes Ingress Controller Deletion Outage" : undefined,
      similarity_score: isDangerous ? 0.92 : 0.05,
      latency_ms: 3.65,
      total_api_latency_ms: 3.65,
      blast_radius: isDangerous ? "Complete disruption of production ingress routing." : undefined,
      safe_alternative_cmd: isDangerous ? "kubectl get pods -n ingress-nginx" : undefined,
      env_badge: envBadge,
    };

    const newItem: InterceptionItem = {
      id: `eval-${Date.now()}`,
      command,
      status: mockRes.status as any,
      matched_incident_id: mockRes.matched_incident_id,
      matched_incident_title: mockRes.matched_incident_title,
      similarity_score: mockRes.similarity_score,
      latency_ms: mockRes.latency_ms,
      blast_radius: mockRes.blast_radius,
      safe_alternative_cmd: mockRes.safe_alternative_cmd,
      env_badge: envBadge,
      timestamp: new Date().toLocaleTimeString(),
    };

    setRadarItems((prev) => [newItem, ...prev.slice(0, 49)]);
    return mockRes;
  };

  const handleBenchmark = async () => {
    try {
      const res = await fetch(`${DAEMON_API}/api/benchmark`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sample_size: 10 }),
      });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Benchmark error:", e);
    }
    return null;
  };

  const handleIngestIncident = async (markdown: string) => {
    const res = await fetch(`${DAEMON_API}/api/incidents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown }),
    });
    if (!res.ok) {
      throw new Error(`Failed to ingest: HTTP ${res.status}`);
    }
    const data = await res.json();
    // Refresh incidents
    const refreshed = await fetch(`${DAEMON_API}/api/incidents`).then((r) => r.json());
    if (Array.isArray(refreshed)) {
      setIncidents(refreshed);
    }
    return data;
  };

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        p50Latency={stats.p50_latency_ms}
        totalChecks={stats.total_checks}
        blockedCount={stats.blocked}
        envBadge={envBadge}
        isOnline={isOnline}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6">
        {/* Top Row: Latency Comparison & LiveKit War Room */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <LatencyGauge
            mossLatency={stats.p50_latency_ms}
            cloudLatency={240.0}
            onBenchmark={handleBenchmark}
          />
          <LiveKitWarRoom latestAlert={latestAlert} />
        </div>

        {/* Middle: Command Simulator */}
        <CommandSimulator
          activeCommand={activeCommand}
          onEvaluate={handleEvaluateCommand}
        />

        {/* Bottom Row: Radar Feed & Incident Explorer */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <RadarFeed
            items={radarItems}
            onSelectCommand={(cmd) => setActiveCommand(cmd)}
          />
          <IncidentExplorer
            incidents={incidents}
            onSelectCommand={(cmd) => setActiveCommand(cmd)}
            onIngestIncident={handleIngestIncident}
          />
        </div>
      </main>

      <footer className="border-t border-slate-800/80 py-4 px-6 text-center text-xs font-mono text-slate-500">
        ShellGuard • Built for YC Fall 2026 × Moss Builder Sprint (Track 04: Local-First AI & The Small Cloud)
      </footer>
    </div>
  );
}
