# WARDOGS Watcher

Meldet neue Posts von [@WARDOGS](https://x.com/WARDOGS) in einen Discord-Kanal.
Läuft rund um die Uhr über GitHub Actions – dein PC muss nicht an sein.
Kein X-API-Key, keine Bezahl-Dienste, keine Abhängigkeiten.

## Wie es funktioniert

`watcher.py` vergleicht den aktuellen Zustand des Accounts mit dem zuletzt gemerkten
Stand in `state.json`. Es gibt zwei Betriebsarten, umschaltbar über `NOTIFY_MODE`:

### `fast` – Tempo vor Inhalt (aktuell eingestellt)

`api.fxtwitter.com` liefert den Beitragszähler des Profils. Steigt er, geht sofort
eine kurze Meldung mit Profil-Link raus. Der Zähler ist praktisch in Echtzeit aktuell,
und weil ein Abruf nur Sekunden dauert, prüft **ein Job fünfmal im Minutentakt** statt
nur einmal – die Reaktionszeit hängt damit an `CHECK_PAUSE` und nicht an GitHubs
Cron-Warteschlange. Von Post bis Discord vergeht so meist unter zwei Minuten.

Der Preis: kein Text, kein Bild. Und der Zähler zählt **jede** Aktivität, also auch
Retweets und Antworten. Bei einem Account, der viel teilt, wird das schnell laut –
bei @WARDOGS sind 17 von 20 Feed-Einträgen Retweets.

### `rich` – Inhalt vor Tempo

Liest den Feed und meldet mit Text, Bild, Zeitstempel und Link, Retweets
herausgefiltert. Quellen in dieser Reihenfolge:

| Quelle | Liefert | Anmerkung |
| --- | --- | --- |
| Nitter-RSS (`nitter.net`) | Post-ID, Text, Bild | Erste Wahl. Weitere Instanzen über `NITTER_HOSTS` als Reserve. |
| `syndication.twitter.com` | dasselbe | Twitters eigener Embed-Endpunkt, kein Login. Antwortet zurzeit fast durchgehend mit `429`. |
| `api.fxtwitter.com` | Beitragszähler | Letzte Rettung, wenn beide Feeds blocken: knappe Meldung ohne Inhalt. |

Der Haken: Nitter spiegelt X nicht in Echtzeit, gemessen hinkt der Feed **10 bis 25
Minuten** hinterher. Blocken die Feeds ganz, während der Zähler einen neuen Beitrag
meldet, fragt der Watcher bis zu fünfmal im Abstand von 20 Sekunden nach, bevor er
auf die knappe Meldung zurückfällt.

Mit `INCLUDE_RETWEETS=1` kommen Retweets mit. Kleine Einschränkung: Der Watcher
vergleicht Post-IDs, und ein Retweet trägt die ID des *ursprünglichen* Posts. Wird
etwas Älteres geteilt, kann die Meldung ausbleiben. Für eigene Posts stimmt der
Vergleich immer.

### In beiden Fällen

Ist keine Quelle erreichbar, endet der Lauf ohne Meldung und der Stand bleibt
unverändert – es geht nichts verloren, der nächste Lauf holt es nach.

## Einrichtung

### 1. Discord-Webhook erstellen

In Discord: **Kanal → Zahnrad (Bearbeiten) → Integrationen → Webhooks → Neuer Webhook**
→ Name und Kanal wählen → **Webhook-URL kopieren**.

Die URL ist ein Passwort-Äquivalent – wer sie hat, kann in deinen Kanal schreiben.
Sie kommt gleich in die GitHub-Secrets und **niemals** in eine Datei im Repo.

### 2. Repository anlegen

Erstelle auf GitHub ein **öffentliches** Repository, z. B. `wardogs-watcher`, und lade
den Inhalt dieses Ordners hoch.

> **Warum öffentlich?** Bei öffentlichen Repos sind Actions-Minuten unbegrenzt. Private
> Repos haben 2000 Minuten/Monat frei – ein 5-Minuten-Takt verbraucht rund 8600
> Minuten/Monat und würde kostenpflichtig. Willst du es privat, stell den Cron in
> `.github/workflows/watch.yml` auf `*/30 * * * *` (~1440 Min/Monat). Geheimnisse
> stehen ohnehin nicht im Code, sondern in den Secrets.

Falls du Git lokal nutzt, im Ordner `wardogs-watcher`:

```bash
git init && git add . && git commit -m "WARDOGS Watcher" && git branch -M main
```

Danach das Remote deines neuen Repos hinzufügen und pushen.

### 3. Webhook als Secret hinterlegen

Im Repo: **Settings → Secrets and variables → Actions → New repository secret**

- Name: `DISCORD_WEBHOOK`
- Secret: die kopierte Webhook-URL

### 4. Erster Testlauf

**Actions**-Tab → Workflow *WARDOGS Watcher* → **Run workflow**.

Beim allerersten Lauf merkt sich das Skript nur den aktuellen Stand und schickt eine
Bestätigung („Überwachung ist aktiv"). Ab dem zweiten Lauf kommen echte Post-Meldungen.

## Anpassen

- **Anderer Account:** `X_HANDLE` in `.github/workflows/watch.yml` ändern (ohne `@`).
  Beim nächsten Lauf startet die Überwachung für den neuen Account von vorne.
- **Anderer Takt:** den `cron`-Ausdruck in derselben Datei anpassen.
- **Betriebsart:** `NOTIFY_MODE` auf `fast` oder `rich` (siehe oben).
- **Reaktionszeit im Schnellmodus:** `CHECK_PAUSE` in Sekunden bestimmt sie direkt –
  eingestellt sind 15 s, also im Mittel rund 8 Sekunden vom Post bis Discord.
  `CHECK_LOOPS` (50) legt fest, wie lange ein Job durchhält: 50 × 15 s ≈ 12 Minuten.
  Nach unten ist bei etwa 10 s Schluss, darunter bringt es nichts mehr – dann
  dominiert die Zeit, die X selbst braucht, bis der Zähler steht.
  Bei privaten Repos die Laufzeit im Blick behalten, dort sind Actions-Minuten
  gedeckelt; bei öffentlichen Repos ist es kostenlos.
- **Mehr/weniger Meldungen pro Lauf:** `MAX_POSTS` als `env` ergänzen (Standard 5).
  Schützt davor, dass ein Nachhol-Lauf 20 Meldungen auf einmal feuert.
- **Nachfassen bei blockierten Quellen:** `TIMELINE_RETRIES` (Standard 5) und
  `TIMELINE_PAUSE` in Sekunden (Standard 20). Höhere Werte erhöhen die Chance auf
  Text und Bild in der Meldung, verlängern aber den Lauf.
- **Nitter-Instanzen:** `NITTER_HOSTS`, mit Komma getrennt, in Reihenfolge der
  Bevorzugung – z. B. `nitter.net,nitter.privacydev.net`. Die erste Instanz, die
  brauchbare Posts liefert, gewinnt. Nützlich, falls `nitter.net` ausfällt; eine
  aktuelle Liste erreichbarer Instanzen findet sich im Nitter-Wiki.
- **Retweets mitmelden:** `INCLUDE_RETWEETS=1` (siehe Einschränkung oben).

## Lokal testen

```bash
DISCORD_WEBHOOK="https://discord.com/api/webhooks/..." python watcher.py
```

Unter PowerShell:

```powershell
$env:DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."; python watcher.py
```

## Gut zu wissen

- **Cron ist nicht sekundengenau.** GitHub stellt geplante Läufe in eine Warteschlange;
  in der Praxis liegen oft 5–20 Minuten zwischen den Läufen, gelegentlich mehr.
- **`state.json` wird vom Workflow zurück ins Repo committet.** Die Commits vom
  `github-actions[bot]` sind normal und gewollt – so weiß der nächste Lauf, wo er stand.
- **Geplante Workflows werden nach 60 Tagen ohne Repo-Aktivität deaktiviert.** Die
  State-Commits gelten als Aktivität; falls es doch mal stoppt, im Actions-Tab wieder
  aktivieren.
- **Fehlschläge siehst du per Mail.** GitHub benachrichtigt dich, wenn ein geplanter
  Workflow scheitert – etwa wenn beide Quellen längere Zeit blocken.
- **Antworten (Replies) werden ignoriert**, solange die Timeline-Quelle funktioniert.
  Im Fallback-Modus zählt der Zähler sie mit.
