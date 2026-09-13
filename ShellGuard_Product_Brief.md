# 🛡️ ShellGuard
**Zero-Latency Terminal Interceptor**
*Product Brief for YC Fall 2026 × Moss: The Zero Latency Builder Sprint*

---

## 1. The Big Picture
**ShellGuard** is an invisible, instant safety net for developers. It lives directly in the terminal and intercepts highly destructive commands *before* they reach the server, using local AI to check if the command has caused an outage in the past.

## 2. The Problem: The "Oh No!" Moment
Every DevOps engineer or backend developer knows the panic of hitting the `Enter` key on a command and instantly realizing they just deleted a production database or applied a broken configuration. 
* Currently, developers have to rely on their own memory to remember every past company incident and architectural rule.
* Once `Enter` is pressed, it is usually too late.

## 3. The Solution: How ShellGuard Works
1. **The Interception:** When a developer types a command (e.g., `kubectl delete namespace prod-db`) and hits `Enter`, ShellGuard presses "Pause".
2. **The 3-Millisecond Search:** In a microscopic fraction of a second, ShellGuard reads the command and searches the company's local folder of past outage reports and safety rules.
3. **The Block:** If it finds a match (e.g., *"Incident #402: Deleting this namespace caused a 4-hour outage last year"*), it blocks the command from executing and flashes a red warning on the screen.
4. **The Pass:** If the command is safe, it runs normally.

## 4. The Secret Weapon: Why This Wins the Hackathon
The core requirement of this hackathon is to use **Moss**, a sub-10ms AI search engine, to build something where speed is an unfair advantage. 
* **If we built this with Cloud AI (OpenAI / Pinecone):** Every time the user hit `Enter`, their terminal would freeze for 1–2 seconds while it checked the internet. The developer would go crazy from the lag and uninstall the tool.
* **By building this with Moss:** The safety check happens entirely on the laptop's RAM in **3 milliseconds**. The developer doesn't even feel the pause. 

This proves to the judges that the product **physically cannot exist without Moss's zero-latency technology.**

## 5. The Demo Video Plan (What we will present)
We will record a 2-minute split-screen video to blow the judges away:
* **Left Screen (Without ShellGuard):** A developer types a bad database command, hits Enter, and the live application immediately goes offline. Panic ensues.
* **Right Screen (With ShellGuard):** The exact same command is typed. The user hits Enter. In 3.2 milliseconds, the terminal flashes red: `[BLOCKED BY SHELLGUARD] Danger: This matches Incident #402. Are you sure?`. The application stays online.

## 6. Technical Architecture (How we will build it)
To keep it simple and achievable before the deadline, the MVP consists of three parts:
1. **The Corpus (Data):** A simple local folder (e.g., `./knowledge/`) containing 10-20 Markdown (`.md`) files acting as past incident reports and company rules.
2. **The Brain (Moss):** A lightweight background script running on the laptop that loads the Markdown files into Moss's super-fast local memory.
3. **The Hook (Interface):** A small Bash or Zsh script (using `PROMPT_COMMAND` or `zshaddhistory`) that catches the terminal input, sends it to the local Moss brain, and either allows or rejects the execution based on the similarity score.

## 7. Privacy & Security (Track 04 Fit)
Because this is built for **Track 04 (Local First AI)**, it is 100% private. Terminal commands contain highly sensitive API keys and IP addresses. With ShellGuard, zero bytes of data are sent to the cloud. Everything runs securely offline on the developer's machine.

---

### Next Steps for the Team
1. Setup the basic Zsh/Bash terminal hook to capture the `Enter` key.
2. Initialize a local Moss project and load 5 fake "Disaster Incident" Markdown files.
3. Connect the terminal hook to Moss and measure the latency!
