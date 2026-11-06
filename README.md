# Dateninfrastruktur Workspace

Der Workspace verwaltet eigenständige Git-Repositories. `repositories.json`
bindet Pfade, tatsächliche Remotes, Defaultbranches und Verantwortlichkeiten.
Der bestehende Checkout-Remote bleibt bis zur Remote-Aktivierung die reale
Identität. Das lokale Architekturrepo hat bis zu seiner Einrichtung kein Remote.

Python 3.12+, Git und für unabhängige Reviews OpenCode 2.x verwenden.

```sh
./workspace status --profile core
./workspace bootstrap --profile core
./workspace sync --repo admin --repo sodata
./workspace verify
./workspace snapshot --profile core --output .runtime/candidates/source-set.json
./workspace review --task "$TASK_ROOT" --phase "$PHASE"
```

`core` umfasst sechs Produkte und Architektur. `extended` wählt die
zusätzlichen Projekte. `status` liest den Stand. `bootstrap` klont fehlende
Repos mit konfiguriertem Remote. `sync` aktualisiert die explizit gewählten
Repos per Fast-forward auf ihrem sauberen Defaultbranch. Vorhandene lokale
Arbeit bleibt erhalten. `verify` prüft Gitgrenzen und Root-Index.
`snapshot` und `review` binden ausschliesslich Commitstände. Mit
`--exclude-untracked` können vorhandene unversionierte Dateien bewusst
ausgeschlossen werden. Andere lokale Änderungen blockieren die Aufnahme.

Exitcodes sind 0 für Erfolg, 1 für Prüf- oder Bearbeitungsfehler und 2 für
ungültige CLI-Argumente. Externe Reviewblocker erscheinen als
`NICHT_PRUEFBAR` mit Ursache.

Der externe Auftrag liefert ein normatives Dateimanifest und seine
Checkliste unter `contracts/`. Ein JSON-Request unter
`.work/requests/<phase>.json` benennt Repos, Basiscommits, Prompt, Reviewer,
Ressourcengrenzen sowie Prüfprozesse und deren Abhängigkeiten. Das Gate
bindet den Auftragsdigest, die exakten Quellstände, die neue Reviewersitzung,
die ausgeführten Assertions und die Belegdateien. Details stehen im
[Reviewformat](docs/review.md).
