# Flight Controller Requirement Standardization Agent
## Offline PC Setup and Execution Guide

---

# BEFORE GOING TO THE OFFICE PC

Bring these from the internet/home PC:

```text
Latest Project Source Code
offline_packages/
frontend/node_modules/
frontend/.next/
```

After extracting, the project should look like:

```text
Flight-controller-requirement-standardization-agent/
│
├── offline_packages/
├── frontend/
│   ├── node_modules/
│   ├── .next/
│   ├── package.json
│   └── package-lock.json
├── src/
├── scripts/
├── config/
├── requirements.txt
└── ...
```

---

# OFFICE PC — SETUP

## 1. Open Project in VS Code

Open the project folder.

Open terminal:

```powershell
Ctrl + `
```

---

## 2. Check Required Software

```powershell
python --version
```

```powershell
node --version
```

```powershell
npm --version
```

```powershell
ollama --version
```

---

## 3. Allow PowerShell Script Execution

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

---

## 4. Create Python Virtual Environment

From the project root:

```powershell
python -m venv .venv
```

---

## 5. Activate Virtual Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

---

## 6. Install Python Dependencies Completely Offline

```powershell
python -m pip install --no-index --find-links=offline_packages -r requirements.txt
```

Verify:

```powershell
pip check
```

---

# FRONTEND SETUP — NO INTERNET REQUIRED

Make sure these folders were already copied:

```text
frontend/node_modules/
frontend/.next/
```

Do NOT run:

```powershell
npm install
```

Do NOT run:

```powershell
npm install next
```

Next.js already exists inside:

```text
frontend/node_modules/next/
```

---

# CHECK NEXT.JS

Go to frontend:

```powershell
cd frontend
```

Check that Next.js exists:

```powershell
Test-Path node_modules\next
```

Expected result:

```text
True
```

Check version:

```powershell
node -p "require('./node_modules/next/package.json').version"
```

---

# START OLLAMA

Check the available model:

```powershell
ollama list
```

Make sure the model used in your `config.yaml` exists.

Example:

```text
gemma3:4b
```

If Ollama is not already running:

```powershell
ollama serve
```

---

# START BACKEND

Open a new VS Code terminal.

```powershell
cd "E:\Projects\Flight-controller-requirement-standardization-agent"
```

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

```powershell
.\.venv\Scripts\Activate.ps1
```

```powershell
scripts\run_api.ps1
```

Keep this terminal running.

---

# START FRONTEND

Open another terminal.

```powershell
cd "E:\Projects\Flight-controller-requirement-standardization-agent\frontend"
```

For development mode:

```powershell
npm run dev
```

Or, if using the already prepared `.next` production build:

```powershell
npm start
```

---

# OPEN APPLICATION

Open:

```text
http://localhost:3000
```

---

# NORMAL DAILY STARTUP

## Terminal 1 — Backend

```powershell
cd "E:\Projects\Flight-controller-requirement-standardization-agent"

Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

.\.venv\Scripts\Activate.ps1

scripts\run_api.ps1
```

---

## Terminal 2 — Frontend

```powershell
cd "E:\Projects\Flight-controller-requirement-standardization-agent\frontend"

npm run dev
```

---

## Terminal 3 — Ollama

Only if Ollama is not already running:

```powershell
ollama serve
```