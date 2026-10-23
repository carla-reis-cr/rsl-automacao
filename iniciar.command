#!/bin/bash
# RSL Automação — inicia no macOS (duplo clique) ou Linux (./iniciar.command)
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "Preparando o ambiente pela primeira vez..."
  python3 -m venv .venv && ./.venv/bin/pip install -q -r requirements.txt
fi
./.venv/bin/python app.py
