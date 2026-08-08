#!/usr/bin/env python3
"""
Beobachtet einen X-(Twitter-)Account und schickt neue Posts an einen Discord-Webhook.

Kein API-Key noetig. Drei Quellen, in dieser Reihenfolge:
  1. Nitter-RSS              -> Post-ID, Text und Bild
  2. syndication.twitter.com -> dasselbe, liefert aktuell meist nur 429
  3. api.fxtwitter.com       -> nur der Post-Zaehler, Meldung ohne Inhalt

Konfiguration ueber Umgebungsvariablen:
  DISCORD_WEBHOOK    (Pflicht)  Webhook-URL des Discord-Kanals
  X_HANDLE           (optional) Account ohne @, Standard: WARDOGS
  MAX_POSTS          (optional) Hoechstzahl Meldungen pro Lauf, Standard: 5
  TIMELINE_RETRIES   (optional) Nachfass-Versuche bei erkanntem Post, Standard: 5
  TIMELINE_PAUSE     (optional) Sekunden zwischen den Versuchen, Standard: 20
  NITTER_HOSTS       (optional) Instanzen mit Komma getrennt, Standard: nitter.net
  INCLUDE_RETWEETS   (optional) 1 = Retweets mitmelden, Standard: 0
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import unquote

HANDLE = os.environ.get("X_HANDLE", "WARDOGS").strip().lstrip("@")
WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
MAX_POSTS = int(os.environ.get("MAX_POSTS", "5"))
TIMELINE_RETRIES = int(os.environ.get("TIMELINE_RETRIES", "5"))
TIMELINE_PAUSE = int(os.environ.get("TIMELINE_PAUSE", "20"))
NITTER_HOSTS = [h.strip() for h in os.environ.get("NITTER_HOSTS", "nitter.net").split(",") if h.strip()]
INCLUDE_RETWEETS = os.environ.get("INCLUDE_RETWEETS", "0") == "1"
STATE_FILE = Path(__file__).resolve().parent / "state.json"
DC = {"dc": "http://purl.org/dc/elements/1.1/"}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
X_BLUE = 0x1D9BF0
NEXT_DATA = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def fetch(url, accept="*/*", timeout=25):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def as_post(tweet):
    text = tweet.get("full_text") or tweet.get("text") or ""
    # t.co-Kurzlinks durch das echte Ziel ersetzen
    for entity in (tweet.get("entities") or {}).get("urls") or []:
        if entity.get("url") and entity.get("expanded_url"):
            text = text.replace(entity["url"], entity["expanded_url"])
    media = (tweet.get("extended_entities") or tweet.get("entities") or {}).get("media") or []
    return {
        "id": tweet["id_str"],
        "text": text.strip(),
        "created_at": tweet.get("created_at", ""),
        "image": media[0].get("media_url_https") if media else None,
        "url": f"https://x.com/{HANDLE}/status/{tweet['id_str']}",
    }


def timeline():
    """Posts des Accounts, neueste zuerst. Leere Liste, wenn die Quelle blockt."""
    url = (
        "https://syndication.twitter.com/srv/timeline-profile/"
        f"screen-name/{HANDLE}?showReplies=false"
    )
    match = NEXT_DATA.search(fetch(url, accept="text/html"))
    if not match:
        return []

    found = {}

    def walk(node):
        if isinstance(node, dict):
            author = (node.get("user") or {}).get("screen_name") or ""
            identifier = node.get("id_str")
            has_text = "full_text" in node or "text" in node
            if identifier and has_text and author.lower() == HANDLE.lower():
                found[identifier] = node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(match.group(1)))
    newest_first = sorted(found.values(), key=lambda t: int(t["id_str"]), reverse=True)
    return [as_post(tweet) for tweet in newest_first]


def html_to_text(fragment):
    """Nitters HTML-Beschreibung in lesbaren Text - echte Ziele statt Kurztext."""
    text = re.sub(r"<br\s*/?>", "\n", fragment).replace("</p>", "\n")

    def link(match):
        ziel, beschriftung = match.group(1), re.sub(r"<[^>]+>", "", match.group(2))
        # Erwaehnungen und Hashtags zeigen auf die Instanz - da ist der Text besser
        return beschriftung if "nitter" in ziel or ziel.startswith("/") else ziel

    text = re.sub(r'<a href="([^"]*)"[^>]*>(.*?)</a>', link, text, flags=re.S)
    text = unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def first_image(fragment):
    """Erstes Bild, ueber den Instanz-Proxy hinweg auf das Original gezogen."""
    match = re.search(r'<img src="([^"]+)"', fragment)
    if not match:
        return None
    quelle = unescape(match.group(1))
    proxy = re.search(r"/pic/(?:orig/)?(.+)$", quelle)
    return "https://pbs.twimg.com/" + unquote(proxy.group(1)) if proxy else quelle


def parse_nitter(feed):
    posts = []
    for item in ET.fromstring(feed).findall("./channel/item"):
        kennung = re.search(r"/status/(\d+)", item.findtext("link") or "")
        if not kennung:
            continue
        urheber = (item.findtext("dc:creator", namespaces=DC) or "").lstrip("@")
        beschreibung = item.findtext("description") or ""
        text = html_to_text(beschreibung)
        # Zwei Formen von Retweet: fremder Urheber, oder eigener Eintrag mit "RT @"
        retweet = urheber.lower() != HANDLE.lower() or text.startswith("RT @")
        if retweet and not INCLUDE_RETWEETS:
            continue
        posts.append(
            {
                "id": kennung.group(1),
                "text": text,
                "created_at": item.findtext("pubDate") or "",
                "image": first_image(beschreibung),
                "url": f"https://x.com/{urheber or HANDLE}/status/{kennung.group(1)}",
            }
        )
    posts.sort(key=lambda post: int(post["id"]), reverse=True)
    return posts


def nitter_timeline():
    for host in NITTER_HOSTS:
        try:
            posts = parse_nitter(fetch(f"https://{host}/{HANDLE}/rss", "application/rss+xml"))
        except Exception as error:
            print(f"Nitter {host} nicht verfuegbar: {error}")
            continue
        if posts:
            print(f"Nitter {host}: {len(posts)} Posts gelesen")
            return posts
        print(f"Nitter {host}: Feed ohne verwertbare Posts")
    return []


def read_timeline():
    """Beste verfuegbare Inhaltsquelle - leere Liste, wenn alle blocken."""
    posts = nitter_timeline()
    if posts:
        return posts
    try:
        posts = timeline()
        print(f"Timeline: {len(posts)} Posts gelesen")
        return posts
    except Exception as error:
        print(f"Timeline nicht verfuegbar: {error}")
        return []


def profile():
    """Profil-Schnappschuss. 'count' steigt, sobald der Account postet."""
    try:
        user = json.loads(fetch(f"https://api.fxtwitter.com/{HANDLE}", "application/json"))["user"]
        return {
            "count": int(user["tweets"]),
            "avatar": (user.get("avatar_url") or "").replace("_normal.", "_400x400."),
            "name": user.get("name") or HANDLE,
        }
    except Exception:
        user = json.loads(fetch(f"https://api.vxtwitter.com/{HANDLE}", "application/json"))
        return {
            "count": int(user["tweet_count"]),
            "avatar": (user.get("profile_image_url") or "").replace("_normal.", "_400x400."),
            "name": user.get("name") or HANDLE,
        }


def send(payload):
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(4):
        request = urllib.request.Request(
            WEBHOOK,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": UA},
        )
        try:
            with urllib.request.urlopen(request, timeout=20):
                return
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < 3:
                time.sleep(float(error.headers.get("Retry-After", 2)) + 1)
                continue
            raise


def announce(post, prof):
    embed = {
        "author": {
            "name": f'{prof["name"]} (@{HANDLE})',
            "url": f"https://x.com/{HANDLE}",
            "icon_url": prof.get("avatar") or None,
        },
        "title": "Neuer Post auf X",
        "url": post["url"],
        "description": post["text"][:4000] or "(kein Text)",
        "color": X_BLUE,
    }
    if post.get("image"):
        embed["image"] = {"url": post["image"]}
    if post.get("created_at"):
        try:
            embed["timestamp"] = parsedate_to_datetime(post["created_at"]).isoformat()
        except (TypeError, ValueError):
            pass
    send({"content": f"\U0001f514 Neuer Post von **@{HANDLE}**", "embeds": [embed]})


def load_state():
    try:
        state = json.loads(STATE_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    # Bei gewechseltem Handle von vorne anfangen
    return state if state.get("handle", HANDLE) == HANDLE else {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", "utf-8")


def main():
    if not WEBHOOK:
        sys.exit("DISCORD_WEBHOOK ist nicht gesetzt - Secret in den Repo-Settings anlegen.")

    state = load_state()
    first_run = not state

    prof = None
    try:
        prof = profile()
        print(f"Profil: {prof['count']} Posts insgesamt")
    except Exception as error:
        print(f"Profil nicht verfuegbar: {error}")

    posts = read_timeline()

    if not posts:
        # Das Rate-Limit der Timeline ist zeitlich begrenzt. Wenn der Zaehler
        # sagt, dass es gerade wirklich etwas zu melden gibt, lohnt sich
        # hartnaeckiges Nachfassen - sonst nur ein einzelner Nachschlag.
        etwas_neu = (
            prof is not None
            and state.get("count") is not None
            and prof["count"] > state["count"]
        )
        if etwas_neu:
            versuche = TIMELINE_RETRIES
        elif state.get("last_id") is None:
            versuche = 1  # Ausgangspunkt nachholen, ohne die Quelle zu fluten
        else:
            versuche = 0
        for nummer in range(1, versuche + 1):
            print(f"Nachfassen {nummer}/{versuche} in {TIMELINE_PAUSE}s ...")
            time.sleep(TIMELINE_PAUSE)
            posts = read_timeline()
            if posts:
                break

    if not posts and prof is None:
        sys.exit("Keine Quelle erreichbar - Lauf abgebrochen, State bleibt unveraendert.")

    if prof is None:
        prof = {"count": state.get("count"), "avatar": None, "name": HANDLE}

    if first_run:
        save_state(
            {
                "handle": HANDLE,
                "last_id": posts[0]["id"] if posts else None,
                "count": prof["count"],
            }
        )
        send(
            {
                "content": f"✅ Überwachung von **@{HANDLE}** ist aktiv - "
                f"ab jetzt landet hier jeder neue Post.\nhttps://x.com/{HANDLE}"
            }
        )
        print("Erster Lauf - Ausgangszustand gespeichert.")
        return

    if posts and state.get("last_id") is None:
        # Timeline zum ersten Mal erreichbar: nur den Startpunkt merken, nichts melden
        state["last_id"] = posts[0]["id"]
        print("Timeline erstmals verfuegbar - Ausgangspunkt gesetzt.")
    elif posts:
        last_id = int(state["last_id"])
        neu = [post for post in posts if int(post["id"]) > last_id]
        for post in reversed(neu[:MAX_POSTS]):  # aeltester zuerst
            announce(post, prof)
            print(f"gemeldet: {post['url']}")
        if len(neu) > MAX_POSTS:
            print(f"{len(neu) - MAX_POSTS} weitere Posts uebersprungen (MAX_POSTS)")
        state["last_id"] = posts[0]["id"]
    elif prof["count"] is not None and state.get("count") is not None:
        # Timeline blockiert - nur der Zaehler verraet, dass etwas passiert ist
        diff = prof["count"] - state["count"]
        if diff > 0:
            send(
                {
                    "content": f"\U0001f514 **@{HANDLE}** hat {diff} neue(n) Post "
                    f"veroeffentlicht.\nhttps://x.com/{HANDLE}"
                }
            )
            print(f"gemeldet ueber Zaehler: +{diff}")

    if prof["count"] is not None:
        state["count"] = prof["count"]
    state["handle"] = HANDLE
    save_state(state)


if __name__ == "__main__":
    main()
