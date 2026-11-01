#!/usr/bin/env bash
# 작업 공간(worktree)마다 한 번 실행한다: 가상환경 생성, 패키지 설치, .env 준비
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if command -v uv >/dev/null 2>&1; then
  [ -d .venv ] || uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -r requirements-dev.txt
else
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON=python3.12
  else
    PYTHON=python3
    echo "python3.12가 없어 $($PYTHON --version)로 진행합니다."
  fi
  [ -d .venv ] || "$PYTHON" -m venv .venv
  .venv/bin/pip install -r requirements-dev.txt
fi

if [ ! -f .env ]; then
  main_worktree="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
  if [ -f "$main_worktree/.env" ] && [ "$main_worktree" != "$(pwd)" ]; then
    cp "$main_worktree/.env" .env
    echo "main 작업 공간의 .env를 복사했습니다."
  else
    cp .env.example .env
    echo ".env.example을 .env로 복사했습니다. 키를 채우세요."
  fi
fi

echo "셋업 완료: .venv/bin/python $(.venv/bin/python --version)"
