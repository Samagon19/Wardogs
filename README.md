# WARDOGS Watcher

Meldet neue Posts von [@WARDOGS](https://x.com/WARDOGS) in einen Discord-Kanal.
Läuft rund um die Uhr über GitHub Actions – dein PC muss nicht an sein.
Kein X-API-Key, keine Bezahl-Dienste, keine Abhängigkeiten.

## Wie es funktioniert

Alle 5 Minuten holt sich `watcher.py` die neuesten Posts und vergleicht sie mit dem
zuletzt gemerkten Stand in `state.json`. Zwei Quellen, in dieser Reihenfolge:

| Quelle | Liefert | Anmerkung |
| --- | --- | --- |
| `syndication.twitter.com` | Post-ID, Text, Bild | Twitters eigener Embed-Endpunkt, kein Login. Cloud-IPs bekommen manchmal ein Rate-Limit. |
| `api.fxtwitter.com` | Post-Zähler | Fallback. Steigt der Zähler, kommt eine Meldung mit Profil-Link (ohne Text). |

Schlagen beide fehl, bricht der Lauf ohne Meldung ab und der Stand bleibt unverändert –
es geht also nichts verloren, der nächste Lauf holt es nach.

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
- **Mehr/weniger Meldungen pro Lauf:** `MAX_POSTS` als `env` ergänzen (Standard 5).
  Schützt davor, dass ein Nachhol-Lauf 20 Meldungen auf einmal feuert.

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
