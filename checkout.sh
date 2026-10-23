#!/usr/bin/env bash

set -u
set -o pipefail

# Neue Repositories hier ergänzen; dateninfrastruktur-checkout bleibt ausgeschlossen.
GITHUB_BASE_URL="https://github.com/sogis"
REPOSITORIES=(
  dateninfrastruktur-datenwerkstatt
  dateninfrastruktur-diagramm
  dateninfrastruktur-agentic-bi-demo-001
  dateninfrastruktur-agentic-bi-demo-002
)

usage() {
  printf 'Verwendung: %s [zielverzeichnis]\n' "${0##*/}"
  printf 'Klont fehlende Repositories und aktualisiert vorhandene mit git pull --ff-only.\n'
  printf 'Standard: Elternverzeichnis des Scripts.\n'
  printf 'Das Zielverzeichnis wird bei Bedarf erstellt.\n'
}

if [[ $# -eq 1 && ( $1 == --help || $1 == -h ) ]]; then
  usage
  exit 0
fi

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi

if [[ $# -eq 1 ]]; then
  if [[ -z $1 || $1 == -* ]]; then
    printf 'Fehler: Bitte ein Zielverzeichnis angeben (Pfade mit "-" mit ./ beginnen).\n' >&2
    usage >&2
    exit 2
  fi
  target_path=$1
else
  target_path="$(dirname -- "${BASH_SOURCE[0]}")/.."
fi

if ! command -v git >/dev/null 2>&1; then
  printf 'Fehler: Git ist nicht installiert oder nicht im PATH verfügbar.\n' >&2
  exit 1
fi

if ! mkdir -p -- "$target_path"; then
  printf 'Fehler: Zielverzeichnis kann nicht erstellt werden: %s\n' "$target_path" >&2
  exit 1
fi

if ! target_dir=$(CDPATH= cd -- "$target_path" && pwd -P); then
  printf 'Fehler: Zielverzeichnis kann nicht geöffnet werden: %s\n' "$target_path" >&2
  exit 1
fi

cloned=0
updated=0
skipped=0
failed=0
skipped_repositories=()
failed_repositories=()

report_failure() {
  printf '[FEHLER] %s: %s\n' "$1" "$2" >&2
  failed=$((failed + 1))
  failed_repositories+=("$1")
}

for repo_name in "${REPOSITORIES[@]}"; do
  repo_dir="$target_dir/$repo_name"

  if [[ ! -e $repo_dir && ! -L $repo_dir ]]; then
    printf '\n[CLONE] %s\n' "$repo_name"
    if git clone "$GITHUB_BASE_URL/$repo_name.git" "$repo_dir"; then
      cloned=$((cloned + 1))
    else
      report_failure "$repo_name" 'Klonen fehlgeschlagen.'
    fi
    continue
  fi

  # .git kann ein Verzeichnis oder eine Datei (z. B. bei einem Worktree) sein.
  # Die Prüfung verhindert, dass Git stattdessen ein übergeordnetes Repo nutzt.
  if [[ ! -d $repo_dir || ( ! -d $repo_dir/.git && ! -f $repo_dir/.git ) ]] ||
    [[ $(git -C "$repo_dir" rev-parse --is-inside-work-tree 2>/dev/null) != true ]]; then
    report_failure "$repo_name" 'Der vorhandene Pfad ist kein eigener Git-Arbeitsbaum.'
    continue
  fi

  if ! repo_status=$(git -C "$repo_dir" status --porcelain --untracked-files=all); then
    report_failure "$repo_name" 'Git-Status konnte nicht ermittelt werden.'
    continue
  fi

  if [[ -n $repo_status ]]; then
    printf '[SKIP] %s: Uncommittete Änderungen oder unversionierte Dateien vorhanden.\n' "$repo_name"
    skipped=$((skipped + 1))
    skipped_repositories+=("$repo_name")
    continue
  fi

  printf '\n[PULL] %s\n' "$repo_name"
  if git -C "$repo_dir" pull --ff-only; then
    updated=$((updated + 1))
  else
    report_failure "$repo_name" 'Pull fehlgeschlagen; siehe Git-Meldung oben.'
  fi
done

printf '\nZusammenfassung:\n'
printf '  Geklont: %s\n  Aktualisiert: %s\n  Übersprungen: %s\n  Fehlgeschlagen: %s\n' \
  "$cloned" "$updated" "$skipped" "$failed"

if [[ $skipped -gt 0 ]]; then
  printf '\nÜbersprungene Repositories:\n'
  printf '  - %s\n' "${skipped_repositories[@]}"
fi

if [[ $failed -gt 0 ]]; then
  printf '\nFehlgeschlagene Repositories:\n'
  printf '  - %s\n' "${failed_repositories[@]}"
fi

if [[ $skipped -gt 0 || $failed -gt 0 ]]; then
  exit 1
fi

exit 0
