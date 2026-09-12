#!/usr/bin/env bash
# Запуск «Моисея» одной командой: окружение -> зависимости -> индекс -> сервер.
set -euo pipefail

cd "$(dirname "$0")"
GREEN='\033[0;32m'; RED='\033[0;31m'; DIM='\033[2m'; NC='\033[0m'
step() { printf "${GREEN}▸${NC} %s\n" "$1"; }
warn() { printf "${RED}!${NC} %s\n" "$1"; }

command -v python3 >/dev/null || { warn "Нужен Python 3.11+"; exit 1; }
command -v npm     >/dev/null || { warn "Нужен Node.js 18+ (npm)"; exit 1; }

PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 11) else 0)')
[ "$PY_OK" = "1" ] || { warn "Нужен Python 3.11 или новее (сейчас $(python3 -V))"; exit 1; }

if [ ! -d .venv ]; then
  step "Создаю виртуальное окружение"
  python3 -m venv .venv
fi
PY=.venv/bin/python

step "Устанавливаю зависимости Python"
$PY -m pip install -q --upgrade pip
$PY -m pip install -q -r backend/requirements.txt

if [ ! -d frontend/node_modules ]; then
  step "Устанавливаю зависимости фронтенда"
  (cd frontend && npm install --no-audit --no-fund --loglevel=error)
fi

step "Собираю фронтенд"
(cd frontend && npm run build >/dev/null)

step "Готовлю поисковый индекс"
(cd backend && ../$PY -m app.ingest.build_index)

if [ ! -f .env ] || ! grep -q '^ANTHROPIC_API_KEY=.\+' .env 2>/dev/null; then
  printf "${DIM}  Ключ ANTHROPIC_API_KEY не задан — автономный режим.\n"
  printf "  Полный режим: cp .env.example .env и вписать ключ.${NC}\n"
fi

step "Запускаю сервер: http://localhost:8000"
cd backend && exec ../$PY -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
