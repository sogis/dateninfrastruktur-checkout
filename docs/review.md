# Unabhängiges Review

Der Auftrag ist ein absoluter Pfad ausserhalb des Workspace. Sein
`contracts/normative-files.json` hat Formatversion 1, Auftragskennung,
Revision und eine explizite Liste relativer normativer Dateipfade.
`contracts/phase-checks.json` verwendet dieselben Kennungen und ordnet
Pflichtchecks den Phasen zu.

Der JSON-Request hat Formatversion 1 und wiederholt Auftrag, Revision und
Phase. `repositories` enthält die benötigten Inventar-IDs, `bases` bindet
jeweils deren Basiscommit und die Workspace-Basis. `review_prompt` bezeichnet
einen normativen Pfad. `reviewer` bindet Provider/Modell, Modellrevision
und öffentliche Quelle. `resources` beschreibt die zulässigen Ressourcen
und Nichtziele. `additional_rules` kann externe Instruktionsdateien des
Auftrags binden.

`checks` weist jeder Pflicht-ID ein Argumentarray `argv`, den erwarteten
Prozessexit `exit`, die tatsächlich benötigten `dependency_files` je Repo
und eine `environment_id` für Toolchain, Runtime und Fixture zu. Der
Testprozess gibt nach seinen Assertions eine eigene Zeile im Format
`ASSERTIONS=<Anzahl> SKIP=0` aus. Für absichtliche Ablehnungen muss das
Prüfprogramm den erwarteten Fehlerzustand positiv bestätigen.
Übernommene Einzelbelege in `carried` verweisen auf ihren Ursprungslauf
und benötigen unveränderte Abhängigkeiten sowie die unabhängige Begründung.

Der Runner legt separate Clones, gebundene Inputs, die Handoff-Datei und
Revieweroutputs im externen Auftrag ab. Die CLI ruft OpenCode mit eigener
Sitzung auf und prüft Provider-/Modell-/Agentmetadaten aus dem bereinigten
Sessionexport. Lokale Regelgrenzen und Vorher-/Nachher-Snapshots dienen der
Integritätsprüfung. Reviewer dürfen die Originale und ihre Credentials
nicht öffnen. Diese Umgebung hat keine zusätzliche OS-Sandbox.
