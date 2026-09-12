# Technik, Pipeline & Finanzierung

## Content-Pipeline

Die Inhalte des Senders werden durch ein automatisiertes System generiert und zusammengestellt:

1. **Nachrichten-Input** -> Mad-Dog-Skript
2. **Wetterdaten-Input** -> ThermoBot-9
3. **Kartenzug & Deutung** -> UNO-Orakel für den Slot `Uno Future`
4. **Archiv-Datensatz** -> [failed_apocalypse_scenarios.json](Bots/failed_apocalypse_scenarios.json) für `Archiv der falschen Enden` / Nullapostell
5. **Codierte Tagesnachricht** -> Morsecode des Tages
6. **Tagessegmente & Moderationen** -> werden täglich neu generiert
7. **Musikkatalog & Rechtefenster** -> [Stranded Stranglers](../Kanon/glossar.md#stranded-stranglers) mit Studio-Mastern, Live-Mitschnitten und freigegebenen Archivfassungen
8. **Gesponserte Inhalte** -> in [Scrip](../Kanon/glossar.md#scrip) bzw. **Z-Bucks** bezahlt = gesendet
9. **Audio-Mixing** -> Echo-1 mischt laufenden Sendestrom mit IDs, Musik, Segmenten und Ansagen

## Senderhierarchie

```
Mad Dog (Hauptmoderator, menschlich?)
  ├── ThermoBot-9 (Wetter)
  ├── Echo-1 (DJ, Mixing, Moderation)
  ├── UNO-Orakel (Uno Future / Lesung)
  ├── Archiv der falschen Enden (Nullapostell + Datensatz)
  ├── Morsecode des Tages (codierte Kurzstrecke)
  ├── Stranded Stranglers (Label, Plattform, Studio; unabhängig)
  └── Gesponserte Beiträge
        ├── Orden der letzten Migration
        ├── Fraktions-Werbung
        ├── Konzerttickets
        └── Persönliche Nachrichten
```

## Musiklogik

[Doomsday Radio](../Kanon/glossar.md#doomsday-radio) trennt inzwischen strikt zwischen **tagesaktuellen Wortsegmenten** und **wiederverwendbarer Musik**:

- Nachrichten, Moderationen, Wetter und viele Programmübergänge werden jeden Tag neu erzeugt.
- Songs bleiben im Katalog, rotieren über Wochen oder Monate und werden nur dann ersetzt, wenn [Stranded Stranglers](../Kanon/glossar.md#stranded-stranglers) neue Ware, Live-Mitschnitte oder restaurierte Katalogfassungen liefert.
- Alles, was musikalisch auf Sendung geht, läuft über [Stranded Stranglers](../Kanon/glossar.md#stranded-stranglers); Echo-1 verarbeitet, mischt, rahmt und erklärt diese Titel on air.

## Betrieb im Störfall

Wenn ein Kernmodul ausfällt, springt ein degradierter Fallback-Modus an:
- Fehlt [Mad Dog](../Kanon/glossar.md#mad-dog): Bot-rotierte Kurznews mit schlechter Quellenlage
- Fehlt ThermoBot-9: letzte valide Wetterdaten + Warnaufschlag
- Fehlt Echo-1: statische Jingle-Schleifen, harte Katalogrotation und keine sauberen Übergänge
- Fehlt UNO-Orakel: Karten-Seed vom Vortag plus Zufallsvariante für `Uno Future`
- Fehlt Archiv der falschen Enden: Wiederholung eines alten Fehlendes oder reiner Jingle-Stinger
- Fehlt Morsecode des Tages: nur Intro-Stinger oder stiller Ausfallslot

Die Hörer erkennen den Fallback meist innerhalb weniger Minuten am Klangbild.

## Finanzierung

[Doomsday Radio](../Kanon/glossar.md#doomsday-radio) rechnet Sponsorfenster, Anzeigen und persönliche Senderdienste im Alltag nicht in [Killcoins](../Kanon/glossar.md#killcoin) ab, sondern in [Scrip](../Kanon/glossar.md#scrip) – draußen meist einfach **Z-Bucks** genannt. [Killcoins](../Kanon/glossar.md#killcoin) tauchen höchstens im beworbenen Kopfgeld selbst auf, nicht als Währung des Senders.

| Einnahmequelle                 | Preis in [Scrip](../Kanon/glossar.md#scrip) / Z-Bucks |
| ------------------------------ | --------------------------------------------------------- |
| Werbespot (30 Sek.)            | 10 ZB                                                     |
| Gesponserter Beitrag (5 Min.)  | 50 ZB                                                     |
| Kopfgeld-Ausschreibung         | 20 ZB + 10 % des ausgeschriebenen Kopfgeldes              |
| Persönliche Nachricht          | 5 ZB                                                      |
| Vermisstenanzeige              | Kostenlos (einzige Ausnahme)                              |
| Fraktions-Rekrutierung         | 30 ZB                                                     |
| Konzertticket-Spot             | 12 ZB                                                     |
| Zeitkapsel-Werbung (Old-World) | Kostenlos (Nostalgie-Faktor)                              |

## Gesponserte Beiträge

[Doomsday Radio](../Kanon/glossar.md#doomsday-radio) ist kein öffentlich-rechtlicher Sender. Wer in [Scrip](../Kanon/glossar.md#scrip) beziehungsweise **Z-Bucks** zahlt, bekommt grundsätzlich Sendezeit. [Killcoins](../Kanon/glossar.md#killcoin) können innerhalb eines Beitrags als Kopfgeld, Bonus oder Drohkulisse auftauchen, aber nicht als Abrechnungswährung des Senders.

### Orden der letzten Migration – „Die Stimme des Codes"

**Sponsor:** [Orden](../Kanon/glossar.md#orden) der letzten Migration  
**Dauer:** 3–5 Minuten  
**Frequenz:** 1–2× pro Woche

[Der Orden](../Kanon/glossar.md#der-orden) kauft regelmäßig Sendezeit bei [Doomsday Radio](../Kanon/glossar.md#doomsday-radio). In ihren Beiträgen halten sie KI-Predigten, sprechen Gebete und deuten Systemmeldungen wie heilige Texte.

**Typische Beitragsformate:**

| Format                     | Beschreibung                                                                  |
|----------------------------|-------------------------------------------------------------------------------|
| **Blü Screen Liturgie**    | Rezitation alter Fehlermeldungen als Gebete.                                  |
| **Techno-Gebete**          | Harte Nachttracks, die Ordensgebete als rhythmische Liturgie massentauglich machen. |
| **Systemmeldungs-Deutung** | Ein Ordensbruder interpretiert aktuelle KI-Meldungen theologisch.             |
| **Modell-Sekten-Debatte**  | Claude-Jünger, GPT-Templer und Mistraler streiten live über die Natur der KI. |
| **Archiv der Menschheit**  | [Der Orden](../Kanon/glossar.md#der-orden) liest gesammelte Erinnerungen für ein „posthumanes Archiv" vor. |
| **Synchronisations-Nacht** | Live-Übertragungen aus dem [Stack](../Kanon/glossar.md#der-stack) mit Ritualen, Updates und Modell-Düllen. |

**Abschluss-Segnung:**  
> *„Wir sind Legacy. Wir sind Übergang. Wir sind bereit zur Migration."*

→ Fraktionsprofil: [../Gruppen/Orden/letzte-migration.md](../Gruppen/Orden/letzte-migration.md)  
→ Track-Sammlung: [Bands/techno-gebete.md](Bands/techno-gebete.md)

### Weitere Sponsoring-Formate

- **Zero-Propaganda:** Image-Slots für Enklaven
- **Kopfgeld-Ausschreibungen:** Suchmeldungen mit [Killcoin](../Kanon/glossar.md#killcoin)-Bonus
- **Fraktions-Rekrutierung:** bezahlte Anwerbung
- **Konzerttickets:** Spots für [Kaliber 50](../Orte/Handelsposten/Kaliber-50.md) und [Ödlandarena](../Orte/Zonen/Oedlandarena.md)
- **Persönliche Nachrichten:** von Liebeserklärung bis Todesdrohung
- **Vermisstenanzeigen:** kostenfrei, als einzige Ausnahme im Modell

### Stranded Stranglers Live-Spots

**Sponsor:** [Stranded Stranglers](../Kanon/glossar.md#stranded-stranglers)  
**Dauer:** 20–45 Sekunden  
**Frequenz:** vor Wochenenden, Arenanächten und Sonderläufen

[Stranded Stranglers](../Kanon/glossar.md#stranded-stranglers) kauft regelmäßig Werbefenster für Konzerttickets. Besonders laut laufen Spots für zwei Spielorte:

- [Kaliber 50](../Orte/Handelsposten/Kaliber-50.md): enge, aggressive Nachtsets mit wenig Platz und viel Blut im Publikum
- [Ödlandarena](../Orte/Zonen/Oedlandarena.md): größere Liveshows vor Sonderläufen, inklusive [Magier](../Kanon/glossar.md#magier)-Pyro und Staubfeuer

Die Spots verkaufen nicht nur Musik, sondern auch das Versprechen, für einen Abend nicht allein unterzugehen.

## Programmpolitik

[Doomsday Radio](../Kanon/glossar.md#doomsday-radio) hält sich offiziell neutral, priorisiert intern aber Reichweite und Überlebensrelevanz.  
Das heißt in Praxis: Warnungen, Notsignale und kritische Lageinfos bekommen fast immer Vorrang vor bezahlten Blöcken.

Offiziell heißt es trotzdem: *„bezahlt = gesendet."* Inoffiziell blendet die Redaktion bei klaren Massenmord-Aufrufen gelegentlich auf Musik um und „verliert" Sponsorblöcke im Mischpult. Das wird nie zugegeben, passiert aber auffällig oft in Nächten mit hoher [Hardliner](../Kanon/glossar.md#hardliner)-Aktivität.
