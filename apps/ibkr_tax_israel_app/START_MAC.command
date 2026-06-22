#!/bin/bash
set -e
cd "$(dirname "$0")"
clear
printf "===============================================\n"
printf "IBKR Israel Tax App - launcher\n"
printf "===============================================\n\n"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/"
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating local Python environment..."
  "$PY" -m venv .venv
fi

source .venv/bin/activate
echo "Installing/updating dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo
echo "Opening the app in your browser..."
echo "If the browser does not open automatically, go to http://localhost:8501"
python -m streamlit run app.py
