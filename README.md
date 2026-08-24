# Running the Flight Controller Requirement Standardization Agent (Offline)

This project can be installed and run on a computer with **no internet connection**.

Before transferring the project to the offline PC, make sure the following are available:

- Python 3.11
- Node.js
- Ollama
- Required Ollama model (`gemma3:4b` or the configured model)
- `offline_packages/` containing all required Python `.whl` files
- `frontend/node_modules/` copied from the development machine
- The complete project source code

---

# Project Setup on the Offline PC

Copy the following to the offline PC:

```text
Flight-controller-requirement-standardization-agent/
│
├── config/
├── data/
├── frontend/
│   ├── app/
│   ├── components/
│   ├── context/
│   ├── hooks/
│   ├── lib/
│   ├── services/
│   ├── types/
│   ├── node_modules/       ← Required for offline frontend
│   ├── package.json
│   ├── package-lock.json
│   └── other frontend configuration files
│
├── offline_packages/       ← Python .whl files
├── scripts/
├── src/
├── tests/
│
├── requirements.txt
├── pyproject.toml
├── README.md
└── Offline_setup.md
```

> Do not copy `.venv/`. A new virtual environment will be created on the offline PC.

---

# Terminal 1 — Ollama

Open a terminal and start Ollama:

```powershell
ollama serve
```

Optionally verify that the required model is available:

```powershell
ollama list
```

Make sure the model configured for the project is available.

For example:

```text
gemma3:4b
```

or:

```text
llama3.1
```

Leave this terminal running.

---

# Terminal 2 — Backend

Open a new PowerShell terminal.

Navigate to the project folder:

```powershell
cd E:\Projects\Flight-controller-requirement-standardization-agent
```

## Create the Python Virtual Environment

This is required only the first time:

```powershell
python -m venv .venv
```

## Activate the Virtual Environment

If PowerShell blocks script execution, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Then activate the environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

You should see:

```text
(.venv) PS E:\Projects\Flight-controller-requirement-standardization-agent>
```

## Install Python Dependencies Completely Offline

First, verify that the offline package folder exists:

```powershell
dir offline_packages
```

Then install all dependencies:

```powershell
python -m pip install --no-index --find-links=offline_packages -r requirements.txt
```

### What this command means

```text
--no-index
```

Prevents `pip` from trying to access the internet.

```text
--find-links=offline_packages
```

Tells `pip` to install the packages from the local `.whl` files inside:

```text
offline_packages/
```

This installation is required only the first time.

## Start the Backend

Run:

```powershell
.\scripts\run_api.ps1
```

The backend should start on:

```text
http://127.0.0.1:8008
```

Leave this terminal running.

---

# Terminal 3 — Frontend

Open another PowerShell terminal.

Navigate to the frontend folder:

```powershell
cd E:\Projects\Flight-controller-requirement-standardization-agent\frontend
```

Before running the frontend, ensure this folder already exists:

```text
frontend/
└── node_modules/
```

This folder must be copied from the development machine because the offline PC cannot download npm packages from the internet.

## Start the Frontend

Run:

```powershell
npm start
```

If the project uses the development script instead, run:

```powershell
npm run dev
```

The frontend should be available at:

```text
http://localhost:3000
```

---

# Verify the Application

All three services should now be running:

```text
Terminal 1 → Ollama Server

Terminal 2 → FastAPI Backend
             http://127.0.0.1:8008

Terminal 3 → Next.js Frontend
             http://localhost:3000
```

Open the application in the browser:

```text
http://localhost:3000
```

The Flight Controller Requirement Standardization Agent should now run completely offline.

---

# First-Time Setup Summary

The following commands are only required once on the offline PC:

```powershell
# Navigate to the project
cd E:\Projects\Flight-controller-requirement-standardization-agent

# Create virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install Python dependencies from local wheel files
python -m pip install --no-index --find-links=offline_packages -r requirements.txt
```

After the first-time setup, you only need to:

```powershell
# Terminal 1
ollama serve
```

```powershell
# Terminal 2
.\scripts\run_api.ps1
```

```powershell
# Terminal 3
cd frontend
npm start
```