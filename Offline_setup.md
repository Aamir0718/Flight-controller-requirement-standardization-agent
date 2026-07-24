# DRDO Flight Controller Requirement Standardization Agent
## Offline Setup Guide (Air-Gapped Environment)


1. Start Ollama:
   ollama serve

2. Start Backend:
  python -m venv .venv
  .\.venv\Scripts\activate
  pip install --no-index --find-links=offline_packages -r requirements.txt
  scripts\run_api.ps1


3. Start Frontend:
   cd frontend
   npm start


This guide explains how to run the project on a computer **without internet access**.

---

# Prerequisites

Ensure the offline machine already has:

- Python 3.11.x installed
- Ollama installed
- Required Ollama model available
  - gemma3:4b (Recommended)
  - OR llama3.1
- Git (optional)
- Node.js (only if frontend needs to be started)

---


# Step 1 — Open three terminals

You will need three terminals.

-----------------------------------------
Terminal 1 : Ollama
-----------------------------------------

Start Ollama.

```bash
ollama serve
```

Leave this terminal running.

(Optional)

Verify installed models:

```bash
ollama list
```

Expected model:

- gemma3:4b

or

- llama3.1

---

# Step 2 — Backend

Navigate to the project.

```powershell
cd Flight-controller-requirement-standardization-agent
```

Create a virtual environment.

```powershell
python -m venv .venv
```

Activate it.

```powershell
.\.venv\Scripts\activate
```

Install dependencies **without internet**.

```powershell
pip install --no-index --find-links=offline_packages -r requirements.txt
```

Run the backend.

```powershell
scripts\run_api.ps1
```

Backend should start on:

```
http://127.0.0.1:8008
```

Verify:

```
FastAPI : Online (8008)
```

---

# Step 3 — Frontend

Open another terminal.

Navigate to frontend.

```powershell
cd frontend
```

Start frontend.

Production:

```powershell
npm start
```

If production is unavailable:

```powershell
npm run dev
```

Frontend should open on:

```
http://localhost:3000
```

---