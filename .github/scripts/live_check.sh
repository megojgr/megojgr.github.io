#!/usr/bin/env bash
# Wartet bis zu $1 Sekunden, bis die echte Seite den Stand $WANT (oder einen neueren) ausliefert.
# Ergebnis als Step-Output ok=true/false. Mit "strict" als zweitem Argument schlägt der Schritt bei false fehl.
limit="${1:-240}"; strict="${2:-}"
url="${URL:-$(bash "$(dirname "$0")/site_url.sh")}"
[ -z "$url" ] && url="$(bash "$(dirname "$0")/site_url.sh")"
ok=false; waited=0
while [ "$waited" -le "$limit" ]; do
  got="$(python3 "$(dirname "$0")/live_gen.py" "$url")"
  if [ -n "$got" ] && python3 -c "import sys,datetime as d;p=d.datetime.fromisoformat;sys.exit(0 if p(sys.argv[1])>=p(sys.argv[2]) else 1)" "$got" "$WANT"; then
    ok=true; break
  fi
  echo "Seite zeigt noch ${got:-nichts} statt $WANT, warte ($waited s) ..."
  sleep 15; waited=$((waited + 15))
done
echo "ok=$ok" >> "$GITHUB_OUTPUT"
if [ "$ok" = true ]; then echo "Seite ist aktuell: $got"; exit 0; fi
echo "::warning::Die Seite zeigt nach $limit s noch nicht den neuen Stand $WANT"
[ "$strict" = strict ] && exit 1
exit 0
