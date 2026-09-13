#!/usr/bin/env bash
# Запуск «Моисея» одной командой: окружение -> зависимости -> индекс -> сервер.
set -euo pipefail

cd "$(dirname "$0")"
GREEN='\033[0;32m'; RED='\033[0;31m'; DIM='\033[2m'; NC='\033[0m'
step() { printf "${GREEN}▸${NC} %s\n" "$1"; }
warn() { printf "${RED}!${NC} %s\n" "$1"; }

# Зафиксированные версии numpy/scipy/scikit-learn/rapidfuzz/lxml в
# backend/requirements.txt вышли до релиза Python 3.14, поэтому под него нет
# готовых wheel-пакетов и pip пытается собрать всё из исходников (падает без
# dev-заголовков и toolchain'а сборки). Поддерживаемый диапазон — 3.10-3.13.
MIN_MINOR=10
MAX_MINOR=13

py_in_range() {
  "$1" -c "import sys; raise SystemExit(0 if (3, $MIN_MINOR) <= sys.version_info[:2] <= (3, $MAX_MINOR) else 1)" 2>/dev/null
}

find_python() {
  local candidates=(python3.12 python3.11 python3.13 python3.10 python3)
  for c in "${candidates[@]}"; do
    if command -v "$c" >/dev/null 2>&1 && py_in_range "$c"; then
      command -v "$c"
      return 0
    fi
  done
  return 1
}

command -v npm >/dev/null || { warn "Нужен Node.js 18+ (npm)"; exit 1; }

PYTHON_BIN="$(find_python || true)"
if [ -z "$PYTHON_BIN" ]; then
  warn "Нужен Python 3.10-3.13 (найден: $(command -v python3 >/dev/null && python3 -V || echo 'не найден'))."
  echo "  На Ubuntu: sudo apt install -y python3.12 python3.12-venv python3.12-dev"
  echo "  Если пакета нет в репозиториях: sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update"
  exit 1
fi
step "Использую интерпретатор: $PYTHON_BIN ($($PYTHON_BIN -V))"

# .venv — воспроизводимый артефакт сборки; если он существует, но собран
# несовместимой версией Python (например, найдена только 3.14 при прошлом
# запуске), пересоздаём его молча, а не падаем на pip install.
if [ -d .venv ] && ! py_in_range .venv/bin/python; then
  warn "Существующее окружение .venv собрано несовместимой версией Python — пересоздаю"
  rm -rf .venv
fi

if [ ! -d .venv ]; then
  step "Создаю виртуальное окружение"
  "$PYTHON_BIN" -m venv .venv
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
