# Redaktionsworkflow

Dieses Dokument beschreibt, wie aus einer kanonischen Geschichte ein sendefähiges Radioformat wird.

## Grundregel

- `content/story/Kanon/` beantwortet: **Was ist in der Welt passiert?**
- `content/story/Radio/` beantwortet: **Wie spielen wir diesen Stoff on air aus?**

Kanon und Ausspielung werden bewusst getrennt gehalten. Änderungen am Weltgeschehen gehören in den Kanon. Änderungen an Form, Dramaturgie, Moderation oder Skript gehören ins Radio.

## Workflow

### 1. Geschichte im Kanon festziehen

Am Anfang steht eine konkrete Geschichte unter [../Kanon/Geschichten/index.md](../Kanon/Geschichten/index.md).

Dort wird festgehalten:

- was passiert ist
- wer beteiligt war
- welche Wendepunkte kanonisch sind
- welcher politische, rechtliche oder mythische Nachhall bleibt

Wenn die Geschichte auf einem allgemeineren Muster beruht, wird dieses unter [../Kanon/Konflikte/index.md](../Kanon/Konflikte/index.md) beschrieben.

### 2. Gleichnamigen Radio-Ordner anlegen

Jede Geschichte, die ausgespielt werden soll, bekommt unter `Radio/` einen eigenen Ordner mit demselben Namen wie die Geschichte.

Beispiel:

- Geschichte: [../Kanon/Geschichten/Die-Jagd-um-Laura.md](../Kanon/Geschichten/Die-Jagd-um-Laura.md)
- Radio-Ausspielung: [Die-Jagd-um-Laura/index.md](Die-Jagd-um-Laura/index.md)

Der Radio-Ordner ist die redaktionelle Bearbeitung der Geschichte, nicht ihr kanonischer Ursprung.

### 3. Formatkurve im Staffelplan festlegen

In `staffelplan.md` wird entschieden, in welcher Form die Geschichte erzählt wird.

Typische Fragen:

- Startet der Stoff als News, Dispatch oder Beobachtung?
- Wann kommen O-Töne und Interviews dazu?
- Wann beginnt die Rekonstruktion?
- Ab welchem Punkt kippt der Stoff ins Hörspiel?
- Wie kehrt der Nachhall wieder in den Funkraum zurück?

Der Staffelplan hält die Gesamtbewegung fest, nicht den genauen Wortlaut.

### 4. Folgenblätter bauen

Unter `folgen/` bekommt jede Folge ein eigenes Blatt.

Jedes Folgenblatt sollte mindestens enthalten:

- Arbeitstitel
- Format
- Moderator oder Sprecherperspektive
- zentrale Beats
- neue Enthüllungen
- bewusst offene Fragen
- Übergang zur nächsten Folge

Hier wird die Dramaturgie pro Episode gebaut.

### 5. Skripte erst nach der Dramaturgie schreiben

Erst wenn Staffelplan und Folgenlogik stehen, entstehen unter `skripte/` die konkreten Sprecherfassungen.

Mögliche Fassungen:

- News- oder Dispatch-Text
- Interviewfassung
- Hybridfassung mit Moderation und Szene
- Hörspielfassung

So wird verhindert, dass schöne Texte geschrieben werden, bevor die Form sauber entschieden ist.

## Arbeitsprinzipien

- Erst Kanon, dann Redaktion
- Geschichte und Radio-Ausspielung tragen denselben Namen
- Konflikte bleiben abstrakt, Geschichten bleiben konkret
- Radio-Dateien verändern keinen Kanon rückwirkend
- Wenn eine neue kanonische Information auftaucht, wird zuerst die Geschichte im Kanon aktualisiert und danach die Radio-Ausspielung nachgezogen

## Kurzform

1. Geschichte unter `Kanon/Geschichten` schreiben oder schärfen.
2. Falls nötig Konfliktmuster unter `Kanon/Konflikte` ergänzen.
3. Gleichnamigen Ordner unter `Radio/` anlegen.
4. In `staffelplan.md` die Formatkurve definieren.
5. Unter `folgen/` die Episodenlogik bauen.
6. Unter `skripte/` die sendefähigen Fassungen schreiben.
