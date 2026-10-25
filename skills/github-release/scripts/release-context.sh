#!/usr/bin/env bash
# release-context.sh — contexto somente-leitura para publicar uma release.
# Uso: bash ~/.config/opencode/skills/github-release/scripts/release-context.sh
set -uo pipefail

say() { printf '\n== %s ==\n' "$1"; }

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "erro: não é um repositório git" >&2
  exit 1
fi

say "repositório"
remote_url="$(git remote get-url origin 2>/dev/null || echo '(sem origin)')"
echo "remote origin : $remote_url"
echo "branch atual  : $(git branch --show-current)"
if command -v gh >/dev/null 2>&1; then
  gh repo view --json nameWithOwner,defaultBranchRef,visibility \
    --jq '"repo          : \(.nameWithOwner) (\(.visibility))\ndefault branch: \(.defaultBranchRef.name)"' \
    2>/dev/null || echo "gh repo view: indisponível"
  echo -n "gh auth       : "
  gh auth status >/dev/null 2>&1 && echo ok || echo "NÃO autenticado (rode: gh auth login)"
else
  echo "gh            : não encontrado no PATH"
fi

say "estado da árvore"
if [ -z "$(git status --porcelain)" ]; then
  echo "limpo"
else
  echo "SUJO — decida o que entra na release antes de continuar:"
  git status --short
fi
echo
git status -sb | head -1

say "última tag"
last_tag="$(git describe --tags --abbrev=0 2>/dev/null || true)"
if [ -z "$last_tag" ]; then
  echo "(nenhuma tag) — primeira release do repositório"
else
  echo "$last_tag  ($(git log -1 --format='%h %ad %s' --date=short "$last_tag"))"
  echo "tipo de objeto: $(git cat-file -t "$last_tag")  (esperado: tag = anotada)"
fi

say "commits desde a última tag"
if [ -n "$last_tag" ]; then
  git log --no-merges --format='%h %s' "$last_tag"..HEAD
  if [ -z "$(git log --no-merges --format='%h' "$last_tag"..HEAD)" ]; then
    echo "(nenhum commit não lançado — não há release a fazer)"
  else
    printf '\n-- sugestão de bump (heurística; confirme no fluxo) --\n'
    range="$last_tag..HEAD"
    if git log --format='%B' "$range" | grep -qE 'BREAKING CHANGE|^[a-z]+(\(.+\))?!:'; then
      echo "major"
    elif git log --format='%s' "$range" | grep -qE '^feat(\(.+\))?!?:'; then
      echo "minor"
    else
      echo "patch"
    fi
  fi
else
  git log --no-merges --format='%h %s' | head -30
fi

say "releases publicadas"
if command -v gh >/dev/null 2>&1; then
  gh release list --limit 5 2>/dev/null || echo "(nenhuma)"
fi

say "declarações de versão detectadas"
if [ -n "$last_tag" ]; then
  old="${last_tag#v}"
  grep -rn --binary-files=without-match \
    -E "(\"version\"[[:space:]]*:[[:space:]]*\"$old\")|(VERSION[[:space:]]*=[[:space:]]*[\"']$old)|(^version[[:space:]]*=[[:space:]]*\"$old\")|(^$old$)" \
    --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=dist \
    --exclude-dir=build --exclude-dir=target --exclude='*.lock' \
    --exclude='bun.lock' --exclude='package-lock.json' \
    . 2>/dev/null | head -20
else
  ls -1 package.json pyproject.toml Cargo.toml VERSION 2>/dev/null || echo "(nada encontrado)"
fi

say "commits de release anteriores (padrão a seguir)"
git log --no-merges -5 --grep='release' --format='%h %s' || true
