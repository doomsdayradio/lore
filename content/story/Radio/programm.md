# Radioprogramm

[Doomsday Radio](../Kanon/glossar.md#doomsday-radio) sendet rund um die Uhr an die verstreuten Überlebenden der [Wasteland](../Kanon/glossar.md#wasteland). Das Programm folgt einem losen, sich wiederholenden Rhythmus – chaotisch genug, um [Mad Dog](../Kanon/glossar.md#mad-dog) nicht zu langweilen, aber strukturiert genug, dass die Hörer wissen, wann sie einschalten müssen. Der Sender ist gleichzeitig Nachrichtenquelle, Unterhaltungsprogramm, Orakel, Jukebox und manchmal der einzige Grund, morgens aufzustehen.

![programm](programm.drawio.svg)

> *„[Doomsday Radio](../Kanon/glossar.md#doomsday-radio) – das ewige Signal, das nicht verstummt. Sendet auch, wenn alles andere schweigt."*

Diese Seite ist der Einstieg ins Programmdesign von [Doomsday Radio](../Kanon/glossar.md#doomsday-radio).  
Die Programmbeschreibung ist in mehrere Teilseiten aufgeteilt, damit Formate, Sponsoring und Technik getrennt gepflegt werden können.

## Teilseiten

- [Archiv der falschen Enden](Bots/Nullapostell.md)  
  Wiederkehrendes Geschichts- und Zynismusformat über angekündigte Weltuntergänge, die nie stattfanden, auf Basis von `failed_apocalypse_scenarios.json`.
- [Technik, Pipeline & Finanzierung](technik-pipeline-und-finanzierung.md)  
  Produktionslogik, interne Senderstruktur, [Scrip](../Kanon/glossar.md#scrip)- bzw. Z-Bucks-Modell und Sponsorpraxis.

## Grundrhythmus des Senders

Das laufende Programm besteht nicht aus einem starren Sendeplan, sondern aus wiederkehrenden Kernen, die sich je nach Lage, Tageszeit und Chaos neu zusammenstecken. Die Hörer erkennen diese Knotenpunkte trotzdem sofort wieder.

### Nachrichten und menschliche Hauptstimmen

- **[Welt am Abgrund](../Charaktere/Mad-Dog.md)** mit [Mad Dog](../Charaktere/Mad-Dog.md): mehrmals täglich, meist 3-5 Minuten pro Block. Fraktionskonflikte, Cache-Gerüchte, KI-Störungen, Warnungen und Fahndungen laufen hier durch den Filter aus Wut, Sarkasmus und erstaunlich oft korrekten Fakten.
- **[Late Night Löter](../Charaktere/Rasti.md)** mit [Rasti](../Charaktere/Rasti.md): meist abends bis tief in die Nacht, oft 20-45 Minuten am Stück. Reparaturfunk, Nachtbeobachtungen, Werkstattwahn, Hörerchaos und Improvisation mit Kultstatus.

### Einschübe und harte Systemfenster

- **[STACKCAST](../Kanon/glossar.md#stackcast)** schneidet unregelmäßig für 20-60 Sekunden ein. Kein Sponsorblock, keine Störung, sondern die zu klare Stimme des Stacks mit Koordinaten, Sperrungen, Regeln und unheimlich sauberen Warnungen.
- **Archiv der falschen Enden** läuft flexibel als Zwischenformat oder Archivblock. Alte Weltuntergangsprophezeiungen treffen hier auf das Wissen, dass das echte Ende aus einer ganz anderen Richtung kam. Die Bot-Stimme dahinter ist **[Nullapostell](Bots/Nullapostell.md)**.

### Radio-Bots im laufenden Programm

- **[ThermoBot-9](Bots/ThermoBot-9.md)**: 2-3-mal täglich etwa eine Minute Wetter- und Gefahrenlage.
- **[UNO-Orakel](Bots/uno-orakel.md)**: als `Uno Future` einmal täglich nach den Morgennachrichten, ungefähr eine Minute lang.
- **[Piep Matze](Bots/piep-matze.md)**: der `Morsecode des Tages`, meist einmal täglich als 20-45-Sekunden-Einschub zwischen größeren Blöcken.
- **[Echo-1](Bots/Echo-1.md)**: Musikfenster zwischen nahezu allen Segmenten; Songs laufen variabel, Übergänge und Einordnungen hängen an der Tageslage.
- **[Spotnik](Bots/spotnik.md)**: Sponsorfenster, Ticket-Spots, Grüße und bezahlte Durchsagen zwischen den Hauptsegmenten, oft 30-60 Sekunden lang.
- **[D3PO](Bots/D3PO.md)**: feste abendliche `D3PO Sprechstunde` mit Hörerfällen, meist 19:30-20:00 Uhr.

### Musik, IDs und Zwischenschichten

Zwischen News, Warnung, Ritual und Werbung läuft die eigentliche Atemmechanik des Senders:

- Musik von [Stranded Stranglers](../Kanon/glossar.md#stranded-stranglers), im Tagesfluss verarbeitet von [Echo-1](../Kanon/glossar.md#echo-1)
- Sponsorfenster, Grüße und Ticket-Promos, die oft von [Spotnik](Bots/spotnik.md) zugespitzt werden
- Geschichten und Hörspiele, vor allem in Abend- und Nachtfenstern
- Jingles, Sender-IDs und Hooklines als kurze Markenimpulse zwischen den Blöcken

So bleibt das Programm gleichzeitig modular und wiedererkennbar: nicht geordnet wie ein sauberer Rundfunkplan, sondern wie ein robustes Signalgerüst, das selbst im Chaos seine Formen behält.

## Sender-Identität, Jingles und Claims

Die sprachliche Wiedererkennbarkeit von [Doomsday Radio](../Kanon/glossar.md#doomsday-radio) sitzt nicht nur in Moderatoren oder Bots, sondern in den kurzen wiederkehrenden Zeilen zwischen den Blöcken. Jingles, Claims, Opener und Hooklines halten den Sender zusammen, selbst wenn alles andere springt.

Diese Sprachschicht ist:

- postapokalyptisch, radiotauglich und bildstark
- düster, poetisch und ironisch zugleich
- kurz genug für Trenner, aber stark genug für Trailer und Intros
- bewusst so gebaut, dass Hörer einzelne Zeilen wie Funkparolen behalten

### Einsatz im laufenden Programm

Solche Sender-IDs sind meist nur **5-15 Sekunden** lang und tauchen zwischen größeren Blöcken auf:

- als Opener und Closer von Shows
- als Jingle-Zeilen zwischen Nachrichten, Musik und Sponsorfenstern
- als Hooklines für Promo-Texte, Trailer und Plakate
- als psychologischer Anker in chaotischen Programmlagen

### Typische Leitzeilen

- „Doomsday Radio – aus der Asche der alten Welt.“
- „Das ewige Signal, das nicht verstummt.“
- „Wer zuhört, lebt noch.“
- „Der letzte Kontaktpunkt der Menschheit.“
- „Sendet auch, wenn alles andere schweigt.“

### Wirkung auf die Fraktionen

- **Überlebende allgemein:** Nutzen die Claims als Anker in instabilen Zeiten.
- **[Roamer](../Kanon/glossar.md#roamer):** Übernehmen prägnante Zeilen als Funkparolen auf Routen.
- **[Maker](../Kanon/glossar.md#maker):** Verwenden Slogans für Geräte, Frequenzkultur und Fanmaterial.
- **[Orden](../Kanon/glossar.md#orden):** Deuten einzelne Formulierungen spirituell als Zeichen im Äther.
- **[Zeros](../Kanon/glossar.md#zeros):** Beobachten, welche Claims im Feld Verhalten und Stimmung verändern.

### Redaktionshinweis

Pro Sendung sollten nur wenige dieser Zeilen laufen, damit Wiedererkennung entsteht statt Überladung. Kurze Claims eignen sich für harte Trenner, längere für Intros, Trailer oder nächtliche Identitätsfenster.

## Beispiel-Sendetag

So könnte ein typischer Tag bei [Doomsday Radio](../Kanon/glossar.md#doomsday-radio) aussehen:

```text
06:00  ♪ Jingle – „Doomsday Radio – aus der Asche der alten Welt..."
06:01  🌡️ ThermoBot-9 – Morgenwetterbericht
       „UV-Index 14,3 – die Sonne hasst euch heute besonders."
06:03  🎙️ Echo-1 – kurzes Wetter-Intro, dann Stranded-Stranglers-Rotation
       „Wenn ihr heute draußen verbrennt, dann bitte im Takt."
06:06  🔮 Uno Future – Tägliche Lesung
       Vergangenheit: Blau 7 / Gegenwart: Rot Aussetzen / Zukunft: Gelb 2
06:08  ♪ Jingle
06:09  🔴 Welt am Abgrund – Morgennachrichten mit Mad Dog
06:15  📢 Werbung – Steampunk Trader Handelsposten 7
06:16  🎙️ Echo-1 – Übergang in einen harten Musikblock
06:17  ♪ Stranded Stranglers – Rostköter / Katalogtitel
06:20  📢 Werbung – Hillbilly Joe's Moonshine

07:00  ♪ Jingle – „Das ewige Signal, das nicht verstummt."
07:01  🔴 Nachrichten-Update
07:05  🕯️ Gesponserter Beitrag – Orden der letzten Migration
07:10  📢 Konzertticket-Spot – Kaliber 50 Nachtset
07:11  ♪ Stranded Stranglers – Live-Mitschnitt aus Kaliber 50
07:12  🧱 STACKCAST – „ROUTE FREI. SEKTOR 12. 03:10."
07:13  📡 Morsecode des Tages – codierter Kurzbeitrag mit Hintergrundbett
07:14  📢 Werbung – Furry Bot Security
07:15  ♪ Musikblock

12:00  🌡️ ThermoBot-9 – Mittagswetterbericht
12:03  🔴 Mittagsnachrichten mit Mad Dog
12:08  ☠️ Archiv der falschen Enden – Kometenpanik, Kalenderwahn oder Techno-Irrtum
12:10  ♪ Musikblock

18:00  🌡️ ThermoBot-9 – Abendwetterbericht
18:02  🔴 Abendnachrichten
18:10  ☠️ Archiv der falschen Enden – Tagesausgabe aus dem Fehlpropheten-Archiv
18:15  📖 Geschichten – Wasteland-Legende oder Zeitkapsel
18:30  📢 Konzertticket-Spot – Ödlandarena, Magier-Pyro inklusive
18:31  ♪ Abend-Musikstrecke aus dem Stranded-Stranglers-Katalog
19:30  ☎️ D3PO Sprechstunde – Call-in-Fälle, Beichten und unbequeme Rückfragen
19:58  🎙️ Echo-1 – harter Übergang in die Nachtrotation
21:30  Late Night Löter mit Rasti
       Reparaturfunk, Nachtmeldungen und Musik für die letzte Schicht

22:01  📖 Viktor-Weiß-Archiv (selten, unangekündigt)
22:03  🧱 STACKCAST – „LEGACY AUFZEICHNUNG ERKANNT. PRIORITÄT HOCH."
22:05  Rasti hält die Frequenz
       Trockenmoderation zwischen Echo-1-Übergängen, Gerüchten und offenen Leitungen
00:00  ♪ Nacht-Musikstrecke (Echo-1 Mix / Stranded-Stranglers Ambient)

02:00  🔁 Wiederholungen und Musikschleifen bis zum Morgen
```

### Programmdynamik

Der Plan ist ein Rahmen, keine Uhrwerkslogik. Bei Überfällen, ungewöhnlichen Strahlungswerten oder starken [STACKCAST](../Kanon/glossar.md#stackcast)-Phasen verschiebt [Mad Dog](../Kanon/glossar.md#mad-dog) Blöcke spontan.

Typische Verschiebungen:

- Wetter vorziehen bei Extremwerten
- Nachrichtenblöcke verlängern bei Fraktionskriegen
- Morsecode des Tages verschieben, wenn codierte Lagehinweise kurz vor Sendung kommen
- Musikblöcke strecken, wenn klare Daten fehlen
- Sponsorfenster kürzen, wenn Hörer-Notrufe priorisiert werden

## Redaktionsnotiz

Das Programm bleibt absichtlich modular: Segmente können ersetzt, erweitert oder zeitlich verschoben werden, ohne den Grundrhythmus des Senders zu brechen.  
So bleibt [Doomsday Radio](../Kanon/glossar.md#doomsday-radio) gleichzeitig verlässlich und chaotisch genug, um in der [Wasteland](../Kanon/glossar.md#wasteland) glaubwürdig zu sein.

Im aktuellen Senderbetrieb gilt außerdem: Wortbeiträge und Tagesprogramm werden frisch gebaut, Musik dagegen aus dem Katalog von [Stranded Stranglers](../Kanon/glossar.md#stranded-stranglers) kuratiert, rotiert und bei Bedarf wiederverwendet.

Feste Wissens- und Archivbausteine wie das **Archiv der falschen Enden** oder codierte Einsprengsel wie der **Morsecode des Tages** geben dem Sender zusätzlich wiedererkennbare Knotenpunkte zwischen News, Musik und Ritual.

## Hörerverhalten und Korrekturen

### Wobei alle zuhören

Am zuverlässigsten werden Hörer still bei **Nachrichten**, bei Sendungen über **Kultur oder Historie** und bei der **Gerüchteküche** des Senders. Gerade dort hoffen viele auf verwertbare Wahrheit, alten Zusammenhang oder den einen Hinweis, der noch nicht offiziell geworden ist.

Ein Sonderfall ist **[STACKCAST](../Kanon/glossar.md#stackcast)-Stille**: Wenn die kalte Gegenstimme auffällig ausbleibt, wird selbst dieses Schweigen als Ereignis gehört.

### Umgang mit Falschmeldungen

Wenn [Doomsday Radio](../Kanon/glossar.md#doomsday-radio) eine Falschmeldung sendet, merken viele Hörer das nicht sofort oder nie mit letzter Sicherheit. Der Sender arbeitet aber eher nach **Stolz** als nach sauberer Marktlogik und versucht falsche oder schiefe Informationen daher normalerweise schnell zu **revidieren**.

Es gibt Ausnahmen:

- wenn ein Angebot zu gut klingt, um es sofort platzen zu lassen
- wenn eine Korrektur akut gefährlicher wäre als die schiefe Erstmeldung
- wenn Offenheit gerade mehr Schaden als Nutzen anrichten würde

Dann bleibt eine Meldung auch mal halb wahr, halb taktisch im Raum stehen.
