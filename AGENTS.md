# AGENTS.md – Dateninfrastruktur-Workspace


## Git und Scope

Der Root ist das Workspace-Repository. Die Einträge in `repositories.json` sind eigenständige Gitrepos; ihre Quellen werden nicht im Root versioniert. Kein Monorepo, keine Submodules/Gitlinks. Gitoperationen nur im verifizierten Toplevel des betroffenen Repos. Kein Sammelcommit fremder Änderungen.

Vor Arbeit tatsächliche lokale Zustände, Remotes, SHAs, Index und fremde Dateien feststellen. Kein implizites Pull/Stash/Reset/Branchwechsel. Produktverantwortung und jeweilige Repo-AGENTS lesen.

## Aufträge und Regeln

Diese Datei aktiviert keinen Auftrag. Der Benutzer-/Startprompt bezeichnet den Auftrag ausdrücklich. Einmalige Spezifikationen und Arbeits-/Reviewberichte liegen ausserhalb der Produktquellen und werden dem Runner als gebundener TASK_ROOT übergeben. Aktuelle Produkt-/Architekturverträge beachten; abgeschlossene alte Aufträge sind keine globalen Regeln.

Aktuelle READMEs beschreiben nur heutige Bedienung. Keine chronologischen Phasenanhänge, keine Ersatzhalde für alte Specs. Historische Inhalte nicht umschreiben; entbehrliche Dateien nach Transfer gültiger Regeln aus dem aktuellen Tree entfernen.

## Implementierung und Review

Codex implementiert. Der unabhängige Reviewer wird autonom über den Workspace-Runner gestartet: OpenCode 2.x, ausdrücklich verlangtes DeepSeek Flash 1017, tatsächlich belegte Provider-/Modellidentität. Keine stille Modellsubstitution.

Reviewer lesen Anforderungen/Quellen, führen passende Tests und eine eigene Gegenprobe aus und prüfen Code und Zielerreichung. Keine Produktreparaturen durch den Reviewer. Nur gebundenes ABGENOMMEN öffnet die nächste Phase. Korrekturen durch Codex, neuer Kandidat, neue Sitzung.

Risikobasiert testen: Fehlerfall, betroffene Verträge und kleinste sinnvolle Regression. Unveränderte Einzelbelege nur mit nachvollziehbarer Nichtbetroffenheit. Auth-/Rechte-/Schema-/Transaktionsänderungen gezielt breiter prüfen. Exit0 ohne relevante Assertions ist kein Erfolg.

## Daten und Laufzeiten

Keine fremden Dateien/Instanzen/Volumes ändern. Tests mit eigener Instanz-ID, Ports, Volumes, Hostpfaden und synthetischen Credentials; vorhandene ComposeContext-Eigentumsprüfung verwenden. Keine zweite Orchestrierung. Keine globale Bereinigung.

Keine Original-`.env`, CSV, Dumps oder Secrets in Git, Logs oder Modellkontext. Konkrete Datenübernahmen brauchen ausdrücklich beauftragten Plan, Sicherung, isolierte Vorabnahme und kontrollierte Nachprüfung. Normale Appstarts verändern das Schema nicht; unbekannte Verträge nicht automatisch «reparieren».

AGENTS ist kein technischer Schreibschutz. Kandidatenisolierung und Integritätsprüfung sind zusätzlich erforderlich. Remote-Push/Merge/Release, Zugänge und Hosting benötigen ausdrückliche Freigabe.

## Architektur und Bereinigung

Technische Ist-Architektur im Architekturrepo, funktionale draw.io-Übersicht getrennt. Beobachtung, verbindliche Regel und Zukunftsplanung nicht vermischen. Relevante Codeänderung erfordert passende Modell-/Quellen-/Testaktualisierung.

Ein aktiver Weg pro Aufgabe. Keine Aliasstarter, retired-Fehlerstubs, doppelten Inventare oder hypothetischen Kompatibilitätsmodi. Historische Migrationen nicht pauschal konservieren; heutige Definitionen und sichere künftige Änderungen erhalten. Codehistorie ist nicht gleich Datenretention. Daten nicht aufgrund alter Namen löschen. Dauerhafte Tests nach Verhalten benennen.

## Zuständigkeiten im Arbeitsbereich

- Das Workspace-Repo verwaltet Inventar, Gitgrenzen und Review. Die tägliche
  Bedienung steht im [Workspace-README](README.md).
- Der Dev-Stack besitzt Compose, Dienstgrenzen, Gateway und Integrationstests.
  Der bestehende gemeinsame PG16/PostGIS-Server nutzt getrennte logische
  Datenbanken. Betriebsbefehle und Kontextprüfung gehören in den Stack.
- Admin besitzt den Managementkatalog, Anlieferung, Autorisierung und
  PostgreSQL-Fachannahme. INTERLIS mit ili2pg erzeugt das Fachschema.
  Apache Cayenne verwendet das gebundene physische Mapping.
- Sodata liest ausschliesslich die freigegebenen Katalogsichten in PostgreSQL.
  APISIX ruft die Admin-Authorization-API per `forward-auth` auf. Der
  interne Origin liefert Dateien aus dem privaten Garage-Bucket.
- Die Jenkins-Laufzeit installiert das lokale GRETL-Plugin und dessen
  geprüftes Bundle. Ein generischer CSVjob führt Lieferungen aus. Admin
  prüft Fachrechte am gesamten logischen Datensatz bei der jeweiligen
  Operation. Technische Parameter oder gecachte Rechte autorisieren nichts.
- Das Themenrepo besitzt die CSV-Verträge und den Runner sowie den
  eigenständigen ClickHouse-Ladeweg. PostgreSQL-Fachannahme und nachfolgende
  ClickHouse-Projektion sind getrennte Zustände.

## Einstieg aus einem Produktrepo

Die Repo-AGENTS beschreibt die lokalen Arbeitsregeln. Bei Arbeit im
gemeinsamen Workspace zusätzlich die Root-AGENTS ausdrücklich lesen.
Die Instruktionsauflösung kann an einer Gitgrenze enden. Ein Einzelclone
ist eigenständig bedienbar. Ein auftragsgemässer Multi-Repo-Vorgang braucht
den verifizierten Workspace sowie die darin bezeichneten Repo-Regeln.

## Schutz bestehender Arbeit

Eindeutig eigene Testressourcen verifizieren, bevor ein Prozess sie ändert
oder entfernt. Keine produktiven Bucket-Writes und keine externen Reloads
ohne gesonderten Auftrag. Keine gemeinsam genutzten Volumes pauschal löschen.
Bestehende Quellen, lokale Daten, Rechte, Identitäten und Auditbelege sichern.
Nur klar zugeordnete Dateien und Repos im vereinbarten Scope ändern.

Phasen- und Betriebsnachweise bleiben bei ihrer tatsächlichen Quelle und
tragen den tatsächlich geprüften Stand. Gegenproben laufen in eigenen
Fixtures. Der Repository-, Vertrags-, Regel- und Prozessnachweis wird vor
dem nächsten Schritt mit dem maschinellen Gate abgeglichen.
