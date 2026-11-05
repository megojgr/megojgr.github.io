#!/usr/bin/env bash
# Startet den nächsten Lauf von daily.yml und prüft, dass er wirklich angelegt wurde. Bis zu 6 Versuche.
start="$(date -u -d '-60 seconds' +%Y-%m-%dT%H:%M:%SZ)"  # etwas Puffer für abweichende Uhren
for i in 1 2 3 4 5 6; do
  if gh workflow run daily.yml --ref main; then
    sleep 20
    n="$(gh run list --workflow daily.yml --limit 10 --json createdAt --jq "[.[] | select(.createdAt >= \"$start\")] | length" 2>/dev/null || echo 0)"
    if [ "${n:-0}" -gt 0 ]; then echo "Nächster Lauf gestartet (Versuch $i)"; exit 0; fi
    echo "Lauf noch nicht zu sehen, versuche erneut ..."
  else
    echo "Start fehlgeschlagen (Versuch $i), neuer Versuch in 30 s ..."
  fi
  sleep 30
done
echo "::error::Der nächste Lauf konnte nicht gestartet werden. Der Wächter (waechter.yml) springt ein."
exit 1
