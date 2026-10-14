# Dateninfrastruktur Checkout

`checkout.sh` klont fehlende Dateninfrastruktur-Repositories und aktualisiert vorhandene
Repositories im angegebenen Zielverzeichnis. Die Repository-Liste ist im Script
hardcodiert; `dateninfrastruktur-checkout` selbst ist nicht enthalten.

Die Liste enthält zunächst `dateninfrastruktur-datenwerkstatt` und
`dateninfrastruktur-diagramm`.

## Voraussetzungen und Aufruf

Bash ab Version 3.2 und Git müssen installiert sein. Das Script funktioniert unter
macOS und Linux. Zum Klonen wird HTTPS verwendet; der Zugriff auf GitHub muss
möglich sein. Für vorhandene Repositories gelten deren konfigurierte Remotes und
Git-Zugangsdaten.

```bash
./checkout.sh
./checkout.sh /pfad/zu/dateninfrastruktur
./checkout.sh "../dateninfrastruktur repos"
./checkout.sh --help
```

Ohne Argument wird das Elternverzeichnis des Scripts verwendet, unabhängig vom
aktuellen Arbeitsverzeichnis. Damit liegen die Repositories standardmässig neben
`dateninfrastruktur-checkout`.

Ein angegebenes Zielverzeichnis hat Vorrang und wird bei Bedarf erstellt.
Explizite relative Pfade beziehen sich auf das aktuelle Arbeitsverzeichnis.
Pfade mit Leerzeichen müssen in Anführungszeichen stehen. Jedes Repository liegt
direkt unter dem Zielverzeichnis, beispielsweise
`/pfad/zu/dateninfrastruktur/dateninfrastruktur-datenwerkstatt`.

## Repositories nachführen

Am Anfang von `checkout.sh` steht das Array `REPOSITORIES`. Dort pro Zeile einen
Repository-Namen ergänzen oder entfernen. `GITHUB_BASE_URL` legt die gemeinsame
GitHub-Basisadresse fest, standardmässig `https://github.com/sogis`.

Die Clone-URL wird als `<GITHUB_BASE_URL>/<repository-name>.git` gebildet. Das
Script sucht beim Ausführen keine zusätzlichen Repositories auf GitHub.

## Verhalten beim Aktualisieren

- Fehlende Repositories werden auf ihrem Default-Branch geklont.
- Vorhandene Repositories werden auf dem aktuell ausgecheckten Branch mit
  `git pull --ff-only` über dessen konfigurierten Upstream aktualisiert.
- Uncommittete Änderungen und unversionierte, nicht ignorierte Dateien führen
  zum Überspringen des Repositorys. Lokale Arbeit bleibt erhalten; es gibt kein
  automatisches Stash oder Zurücksetzen.
- Bei divergierender Historie, fehlendem Upstream, Detached HEAD oder anderen
  Git-Fehlern wird der Fehler gemeldet und das nächste Repository bearbeitet.
- Vorhandene Pfade ohne eigenen Git-Arbeitsbaum werden als Fehler gemeldet und
  nicht überschrieben.

Am Ende erscheinen die Anzahl geklonter und aktualisierter Repositories sowie
die Anzahl und Namen übersprungener oder fehlgeschlagener Repositories.
«Aktualisiert» umfasst auch erfolgreiche Pulls, bei denen bereits alles aktuell war.
Bei fehlendem Git oder einem nicht erstellbaren bzw. nicht zugänglichen
Zielverzeichnis bricht das Script sofort ab.

| Exitcode | Bedeutung |
| --- | --- |
| `0` | Alle Repositories erfolgreich bearbeitet oder Hilfe angezeigt. |
| `1` | Mindestens ein Repository übersprungen/fehlgeschlagen oder ein Fehler bei den Voraussetzungen. |
| `2` | Ungültiger Aufruf, beispielsweise mehrere Argumente oder ein leerer Zielpfad. |
