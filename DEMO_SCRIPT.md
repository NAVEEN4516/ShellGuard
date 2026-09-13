# ShellGuard: 2-Minute Video Demo Script
**Competition:** YC Fall 2026 × Moss: The Zero Latency Builder Sprint  
**Track:** Track 04 — Local-First AI & The Small Cloud  
**Duration:** Exactly 2 minutes (120 seconds)  

---

## Shot 1: The Hook & The Problem (0:00 - 0:25)
* **Visual:** Close-up of an SRE terminal at 2:00 AM. Terminal prompt shows `production-us-east-1`.
* **Voiceover:**
  > "Every SRE and DevOps engineer has lived through this nightmare: You are debugging a stuck ingress pod under pressure. You type `kubectl delete namespace ingress-nginx`, hit Enter... and immediately realize you just nuked production edge routing for the entire company.
  > 
  > Why does this happen? Because company post-mortems and safety rules are trapped in slow Confluence pages or cloud docs. If you used traditional cloud AI to check every keystroke, a 300ms cloud vector round-trip would make your terminal unbearable to use."

---

## Shot 2: Introducing ShellGuard & The Moss Moat (0:25 - 0:45)
* **Visual:** Switch to split-screen showing the terminal on the left and the **ShellGuard Web Cockpit** on the right at `http://localhost:8080`.
* **Voiceover:**
  > "Meet **ShellGuard**: the zero-latency, local-first terminal interceptor built on **Moss**.
  > 
  > Instead of querying an external vector database over the internet, ShellGuard loads historical disaster post-mortems and architecture rules directly into local memory.
  > 
  > Using Moss's in-process Rust runtime, semantic checks take **under 6 milliseconds**—completely imperceptible to the human developer, until it saves the company."

---

## Shot 3: The Live Interception Demo (0:45 - 1:15)
* **Visual:** In the terminal, run `kubectl get pods -n production`.
* **Action:** The command executes instantly in 0.01ms.
* **Voiceover:**
  > "Safe, diagnostic commands like `kubectl get pods` bypass with zero overhead in five microseconds."
* **Action:** Now type `kubectl delete namespace ingress-nginx` and hit Enter.
* **Visual:** INSTANT RED ALERT in terminal and Web Cockpit simultaneously.
  * Terminal flashes: `🛑 [SHELLGUARD BLOCKED] EXECUTION PREVENTED`
  * Displays: `Matched Incident #402 (100% similarity) in 5.8ms`
  * Shows Blast Radius: `48 microservices routing wiped out`
  * Shows Safe Alternative: `kubectl rollout restart deployment/ingress-nginx-controller`
* **Voiceover:**
  > "Boom! The moment you hit Enter, ShellGuard intercepts the command in 5.8 milliseconds. It maps the destructive intent against Incident #402, aborts execution before the Kubernetes API is touched, and hands you the pre-flight verified rolling restart command."

---

## Shot 4: Live Latency Benchmark & Local-First Proof (1:15 - 1:45)
* **Visual:** Click "Run Live 10-Query Benchmark Test" in the Web Cockpit.
* **Visual:** Watch the live gauge animate:
  * Moss in-process: **5.8 ms**
  * Cloud Vector DB baseline: **246.4 ms**
  * Callout: **40x Faster | Zero Network Hops | 100% Offline**
* **Action:** Turn off Wi-Fi (Airplane mode) and run `rm -rf /`. It blocks in 3.7ms offline!
* **Voiceover:**
  > "Look at our live benchmark: Moss runs at 5.8 milliseconds—over 40 times faster than Pinecone or Qdrant.
  > 
  > And because it's built for Track 4, it is 100% local-first. We can unplug the internet completely, and your internal code, passwords, and incident memory never leave your laptop."

---

## Shot 5: Conclusion & The Vision (1:45 - 2:00)
* **Visual:** Return to full camera / logo graphic with GitHub URL.
* **Voiceover:**
  > "ShellGuard proves that when retrieval is under 10 milliseconds, AI stops being a slow chat window and becomes an invisible, real-time safety layer for developers.
  > 
  > ShellGuard: Zero latency. Zero cloud leakage. Zero downtime. Built for the YC Fall 2026 Moss Sprint."
