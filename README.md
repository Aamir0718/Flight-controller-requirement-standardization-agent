Flight Controller Requirements Platform

Easy Setup Guide

Hi!

Follow these steps one by one. You need 3 terminals.

================================================== STEP 1 - Clone the
project (Only the first time)
==================================================

git clone

cd Flight-controller-requirement-standardization-agent

================================================== TERMINAL 1 - Backend
(Python) ==================================================

1.  Open a terminal in the project folder.

2.  Activate the virtual environment:

Windows:

..venv

3.  Tell Python where the source code is:

$env:PYTHONPATH=“src”

4.  Start the backend:

scripts_api.ps1

If everything is correct, you should see something like:

Uvicorn running on: http://127.0.0.1:8000

Open this in your browser:

http://127.0.0.1:8000/health

You should see:

{“status”:“ok”}

If you see this, the backend is working.

================================================== TERMINAL 2 - Ollama
==================================================

Check if Ollama is installed:

ollama list

If gemma3:4b is missing:

ollama pull gemma3:4b

If llama3.1 is missing:

ollama pull llama3.1

Now start Ollama:

ollama serve

If it says it is already running, that is completely fine.

================================================== TERMINAL 3 - Frontend
(Website) ==================================================

Open another terminal.

Go inside the frontend folder:

cd frontend

Only the first time:

npm install

Every time after that:

npm run dev

Now open:

http://localhost:3000

The website should open.

================================================== RUN ORDER
==================================================

Always start everything in this order:

Terminal 1

..venv

$env:PYTHONPATH=“src”

scripts_api.ps1

Terminal 2

ollama serve

Terminal 3

cd frontend

npm run dev

================================================== HOW TO CHECK
EVERYTHING ==================================================

Backend: http://127.0.0.1:8000/health

Frontend: http://localhost:3000

If both open correctly, everything is running.

================================================== HOW TO USE THE
PROJECT ==================================================

1.  Open the website.

2.  Upload an Excel (.xlsx) file.

3.  Click Start Pipeline Analysis.

4.  Wait for the processing to finish.

5.  Review the AI-generated requirement suggestions.

6.  Accept or reject the recommendation.

7.  Export the final reviewed Excel file.

================================================== IF SOMETHING DOESN’T
WORK ==================================================

Backend not running? Run:

scripts_api.ps1

Backend health page should open: http://127.0.0.1:8000/health

------------------------------------------------------------------------

Frontend not opening?

Go to frontend:

cd frontend

Run:

npm install

Then:

npm run dev

------------------------------------------------------------------------

Ollama error?

Run:

ollama serve

------------------------------------------------------------------------

Model missing?

Run:

ollama pull gemma3:4b

or

ollama pull llama3.1

================================================== THAT’S IT!
==================================================

Once these three terminals are running, the complete application will
work.

Happy Coding!
