#!/usr/bin/env bash
# Wächter: startet daily.yml neu, wenn die Seite zu alt ist oder die stündliche Kette abgerissen ist.
url="$(bash "$(dirname "$0")/site_url.sh")"
got="$(python3 "$(dirname "$0")/live_gen.py" "$url")"
age=9999
[ -n "$got" ] && age="$(python3 -c "import sys,datetime as d;print(int((d.datetime.now(d.timezone.utc)-d.datetime.fromisoformat(sys.argv[1])).total_seconds()//60))" "$got")"
since="$(date -u -d '-25 minutes' +%Y-%m-%dT%H:%M:%SZ)"
runs="$(gh run list --workflow daily.yml --limit 20 --json status,createdAt)"
active="$(echo "$runs" | python3 -c "import json,sys;print(sum(r['status'] in ('in_progress','queued','waiting','pending','requested') for r in json.load(sys.stdin)))")"
recent="$(echo "$runs" | python3 -c "import json,sys;print(sum(r['createdAt']>=sys.argv[1] for r in json.load(sys.stdin)))" "$since")"
echo "Stand der Seite: ${got:-unbekannt} (vor $age Min.), aktive Läufe: $active, in den letzten 25 Min. gestartet: $recent"
if [ "$recent" -gt 0 ]; then echo "Gerade läuft schon ein frischer Lauf: nichts zu tun"; exit 0; fi
if [ "$age" -gt 80 ]; then
  echo "::warning::Seite ist $age Minuten alt: starte einen neuen Lauf"
  bash "$(dirname "$0")/dispatch.sh"; exit $?
fi
if [ "$active" -eq 0 ]; then
  echo "::warning::Keine wartende Kette gefunden: starte die stündliche Kette neu"
  bash "$(dirname "$0")/dispatch.sh"; exit $?
fi
echo "Alles in Ordnung"
