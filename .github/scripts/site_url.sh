#!/usr/bin/env bash
# Adresse der veröffentlichten Seite aus dem Repository-Namen (Benutzerseite oder Projektseite)
owner="${GITHUB_REPOSITORY%%/*}"; name="${GITHUB_REPOSITORY#*/}"
if [ "$(echo "$name" | tr 'A-Z' 'a-z')" = "$(echo "$owner" | tr 'A-Z' 'a-z').github.io" ]; then
  echo "https://$owner.github.io/"
else
  echo "https://$owner.github.io/$name/"
fi
