# Umzug zu Cloudflare mit Zugangsschutz

Ziel: Die Seite liegt bei Cloudflare statt bei GitHub Pages und ist nur für Personen sichtbar, die du freigibst.
Die Daten werden weiter stündlich von GitHub gebaut und dann automatisch zu Cloudflare hochgeladen.

Alles hier ist kostenlos. Für Teil B (Zugangsschutz) kann Cloudflare eine Zahlungsmethode zur Bestätigung verlangen,
auch beim kostenlosen Plan. Wenn das passiert und du das nicht willst, brich dort ab, der Rest funktioniert trotzdem.

Wichtig: In Cloudflare **nicht** „Repository verbinden / Import a repository“ wählen. Die fertige Seite liegt nicht im
Repository, sie wird von GitHub Actions gebaut und von dort hochgeladen. Wer das Repository verbindet, baut eine leere Seite.

Der Name der Seite ist `mego-news`, die Adresse wird `https://mego-news.<dein-Teamname>.workers.dev`.
Anderer Name gewünscht: in GitHub unter *Settings* → *Secrets and variables* → *Actions* → Reiter *Variables* die
Variable `CF_PROJECT` anlegen.

## Teil A: Seite bei Cloudflare veröffentlichen

1. **Konto anlegen:** https://dash.cloudflare.com/sign-up mit deiner E-Mail-Adresse, E-Mail bestätigen.
2. **Konto-ID kopieren:** Im Dashboard *Workers & Pages* öffnen. Die *Account ID* steht rechts in der Seitenleiste
   (oder unten links im Menü hinter dem Konto). Kopieren.
3. **Subdomain für Workers:** Wenn Cloudflare in *Workers & Pages* nach einer „workers.dev subdomain“ fragt,
   einen Namen wählen (zum Beispiel `mego`). Gibt es die Frage nicht, ist es schon erledigt.
4. **API-Token erstellen:** Oben rechts Profilsymbol → *My Profile* → *API Tokens* → *Create Token* →
   Vorlage *Edit Cloudflare Workers* → *Use template*. *Account Resources*: dein Konto, *Zone Resources*:
   *All zones* (oder die Auswahl lassen, wie sie ist) → *Continue to summary* → *Create Token*.
   Den Token sofort kopieren, er wird nur einmal angezeigt.
5. **Beides in GitHub eintragen** (Repository `megojgr/megojgr.github.io`):
   *Settings* → *Secrets and variables* → *Actions* → *New repository secret*. Zwei Secrets anlegen:
   - `CLOUDFLARE_API_TOKEN` = der Token aus Schritt 4
   - `CLOUDFLARE_ACCOUNT_ID` = die ID aus Schritt 2

   Oder in der PowerShell (fragt nach dem Wert, nichts steht im Verlauf):
   ```
   gh secret set CLOUDFLARE_API_TOKEN --repo megojgr/megojgr.github.io
   gh secret set CLOUDFLARE_ACCOUNT_ID --repo megojgr/megojgr.github.io
   ```
6. **Lauf starten:** GitHub → *Actions* → *Tägliche News* → *Run workflow*. Nach ein bis zwei Minuten
   steht die Seite bei Cloudflare unter *Workers & Pages* → `mego-news`, die Adresse steht dort bei
   *Domains & Routes*. Kommt der Lauf mit einem Fehler zurück, sag mir Bescheid.

## Teil B: Zugangsschutz (Cloudflare Access)

7. **Schutz einschalten:** *Workers & Pages* → `mego-news` → *Settings* → *Domains & Routes* → in der Zeile
   `…workers.dev` auf *Enable Cloudflare Access*. Cloudflare legt eine Zugangsregel an und führt dich zur
   Verwaltung (*Zero Trust*). Beim ersten Mal einen Teamnamen wählen und den *Free*-Plan nehmen (bis 50 Personen).
8. **Freigegebene Personen eintragen:** In Zero Trust unter *Access* → *Applications* die neue Anwendung öffnen →
   *Policies* → Regel *Allow* → *Include* → *Emails*: deine E-Mail-Adresse und die der Personen, die du freigeben willst.
   Login-Methode: *One-time PIN* (Code per Mail). Session Duration auf `1 month` stellen, dann meldest du dich
   nur einmal im Monat an.
9. **Testen:** Die Adresse in einem privaten Fenster öffnen. Es muss nach der E-Mail fragen. Mit einer nicht
   freigegebenen Adresse darf es keinen Code geben.

Neue Personen später freigeben: *Access* → *Applications* → deine Anwendung → *Policies* → E-Mail ergänzen.

## Teil C: GitHub Pages abschalten

Erst machen, wenn Teil A und B laufen, sonst ist die Seite kurz weg.

10. GitHub → *Settings* → *Secrets and variables* → *Actions* → Reiter *Variables* → *New repository variable*:
    Name `PAGES_OFF`, Wert `true`. Damit lässt der Lauf GitHub Pages aus.
11. GitHub → *Settings* → *Pages* → die drei Punkte beim Eintrag → *Unpublish site*.
    Danach ist `https://megojgr.github.io` nicht mehr erreichbar.

## Teil D: Handy

12. Auf dem Handy die neue Adresse öffnen, mit E-Mail und Code anmelden, dann *Zum Startbildschirm hinzufügen*.
    Das alte Symbol (GitHub-Adresse) löschen.
13. Token (Aktualisieren-Knopf) und Depot-Passwort einmal neu eintragen: Der Browser-Speicher gilt pro Adresse,
    die neue Adresse startet leer. Das Token ist nur nötig, wenn du sofort aktualisieren willst.

## Was öffentlich bleibt und was nicht

- Das Repository bleibt öffentlich (nur dann sind die GitHub-Läufe kostenlos unbegrenzt). Dort liegen der Code,
  die Konfiguration und kleine Zwischenspeicher mit Schlagzeilen und Terminen. Keine Depotdaten, das Depot liegt
  verschlüsselt nur in der Seite selbst.
- Die fertige Seite mit allen Daten liegt nach dem Umzug nur noch bei Cloudflare hinter dem Login.
- Passwörter, Token und Secrets gehören nie in das Repository oder in den Chat.
