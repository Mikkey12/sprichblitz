# Sicherheitsrichtlinie

## Sicherheitslücken melden

Bitte veröffentliche vermutete Sicherheitslücken nicht als Issue und nicht in
einer Diskussion. Nutze im GitHub-Repository unter **Security → Advisories → New
draft security advisory** die private Meldung. Falls diese Funktion noch nicht
aktiviert ist, melde nur, dass ein privater Kontaktkanal benötigt wird, ohne
technische Details oder Geheimnisse offenzulegen.

Eine hilfreiche Meldung enthält:

- betroffene Komponente und Version beziehungsweise Commit;
- nachvollziehbare, möglichst minimale Schritte zur Reproduktion;
- erwartete und tatsächliche Auswirkung;
- eine Einschätzung, ob Zugangsdaten, Audio oder Transkripte betroffen sein
  könnten.

Sende keine echten Bearer-Token, Provider-Keys, Vault-Keys, Audiodateien oder
Transkripte. Verwende markierte Testwerte und schwärze Screenshots sowie Logs.
Falls ein echtes Geheimnis offengelegt wurde, widerrufe beziehungsweise rotiere
es sofort; eine Löschung aus einem Issue oder Commit macht es nicht wieder
geheim.

Der Eingang wird nach Möglichkeit innerhalb von sieben Tagen bestätigt. Weitere
Details, eine Behebung und die koordinierte Veröffentlichung werden anschliessend
im privaten Advisory abgestimmt.

## Unterstützte Versionen

Sicherheitskorrekturen gelten für den aktuellen Stand des Standard-Branches. Für
ältere Commits oder privat veränderte Deployments besteht keine garantierte
Unterstützung.

## Sicherheitsgrenzen

Sprichblitz ist selbstgehostete Software. Betreiber sind insbesondere für TLS,
Zugriffsschutz, Updates, Backups und die sichere Aufbewahrung des
`SPRICHBLITZ_SECRET_KEY` verantwortlich. Provider erhalten Audio oder Text genau
dann, wenn die effektive Moduskonfiguration sie verwendet; lokale Verarbeitung
ist keine Eigenschaft jedes Modus, sondern eine Betriebs- und Nutzerwahl.
