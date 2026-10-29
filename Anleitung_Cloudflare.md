# Umzug zu Cloudflare Pages mit Zugangsschutz

Ziel: Die Seite liegt bei Cloudflare statt bei GitHub Pages und ist nur für Personen sichtbar, die du freigibst.
Die Daten werden weiter stündlich von GitHub gebaut und dann automatisch zu Cloudflare hochgeladen.

Alles hier ist kostenlos. Für Schritt 7 (Zugangsschutz) kann Cloudflare eine Zahlungsmethode zur Bestätigung verlangen,
auch beim kostenlosen Plan. Wenn das passiert und du das nicht willst, brich dort ab, der Rest funktioniert trotzdem.

Als Namen sind vorgesehen: Projekt `mego-news`, Adresse `https://mego-news.pages.dev`.
Ist der Name vergeben, nimm einen anderen und trage ihn in Schritt 6 als Variable `CF_PROJECT` ein.

## Teil A: Seite bei Cloudflare veröffentlichen

1. **Konto anlegen:** https://dash.cloudflare.com/sign-up mit deiner E-Mail-Adresse, E-Mail bestätigen.
2. **Projekt anlegen:** Im Dashboard links *Workers & Pages* → *Create* → Reiter *Pages* → *Upload your static files*
   (Direct Upload). Projektname `mego-news`, dann *Create project*. Als Datei lädst du irgendeine kleine Textdatei hoch
   und klickst *Deploy site*. Das ist nur, damit das Projekt existiert, den Inhalt liefert später GitHub.
3. **Konto-ID kopieren:** Im Dashboard *Workers & Pages* → rechts in der Seitenleiste steht *Account ID*. Kopieren.
4. **API-Token erstellen:** Oben rechts auf das Profilsymbol → *My Profile* → *API Tokens* → *Create Token* →
   *Create Custom Token*. Name `mego-news`. Berechtigung: *Account* → *Cloudflare Pages* → *Edit*.
   *Account Resources*: dein Konto. *Continue to summary* → *Create Token*. Den Token sofort kopieren,
   er wird nur einmal angezeigt.
5. **Beides in GitHub eintragen** (Repository `megojgr/megojgr.github.io`):
   *Settings* → *Secrets and variables* → *Actions* → *New repository secret*. Zwei Secrets anlegen:
   - `CLOUDFLARE_API_TOKEN` = der Token aus Schritt 4
   - `CLOUDFLARE_ACCOUNT_ID` = die ID aus Schritt 3

   Oder in der PowerShell (fragt nach dem Wert, nichts steht im Verlauf):
   ```
   gh secret set CLOUDFLARE_API_TOKEN --repo megojgr/megojgr.github.io
   gh secret set CLOUDFLARE_ACCOUNT_ID --repo megojgr/megojgr.github.io
   ```
6. **Lauf starten:** GitHub → *Actions* → *Tägliche News* → *Run workflow*. Nach ein bis zwei Minuten sollte
   `https://mego-news.pages.dev` die Seite zeigen. (Anderer Projektname: *Settings* → *Secrets and variables* →
   *Actions* → Reiter *Variables* → `CF_PROJECT` = dein Name.)

## Teil B: Zugangsschutz (Cloudflare Access)

7. **Zero Trust öffnen:** https://one.dash.cloudflare.com → beim ersten Mal einen Teamnamen wählen und den
   *Free*-Plan nehmen (bis 50 Personen).
8. **Anwendung anlegen:** *Access* → *Applications* → *Add an application* → *Self-hosted*.
   - Name: `Mego News`
   - Session Duration: `1 month` (dann musst du dich nur einmal im Monat anmelden)
   - Application domain: `mego-news.pages.dev`, und füge eine zweite Zeile mit `*.mego-news.pages.dev` hinzu
     (schützt auch die Vorschau-Adressen)
9. **Regel anlegen:** Policy-Name `Freigegeben`, Aktion *Allow*, Regel *Include* → *Emails* → deine
   E-Mail-Adresse und die der Personen, die du freigeben willst. Speichern.
   Login-Methode: *One-time PIN* (Code per Mail), ohne weiteres Konto.
10. **Testen:** `https://mego-news.pages.dev` in einem privaten Fenster öffnen. Es muss nach der E-Mail fragen.
    Mit einer nicht freigegebenen Adresse darf es keinen Code geben.

Neue Personen später freigeben: *Access* → *Applications* → *Mego News* → *Policies* → E-Mail ergänzen.
Entfernen: E-Mail löschen, optional unter *Users* die Sitzung sperren.

## Teil C: GitHub Pages abschalten

Erst machen, wenn Teil A und B laufen, sonst ist die Seite kurz weg.

11. GitHub → *Settings* → *Secrets and variables* → *Actions* → Reiter *Variables* → *New repository variable*:
    Name `PAGES_OFF`, Wert `true`. Damit lässt der Lauf GitHub Pages aus.
12. GitHub → *Settings* → *Pages* → die drei Punkte beim Eintrag → *Unpublish site*.
    Danach ist `https://megojgr.github.io` nicht mehr erreichbar.

## Teil D: Handy

13. Auf dem Handy die neue Adresse öffnen, mit E-Mail und Code anmelden, dann *Zum Startbildschirm hinzufügen*.
    Das alte Symbol (GitHub-Adresse) löschen.
14. Token (Aktualisieren-Knopf) und Depot-Passwort einmal neu eintragen: Browser-Speicher gilt pro Adresse,
    die neue Adresse startet leer. Das Token ist ohnehin nur nötig, wenn du sofort aktualisieren willst.

## Was öffentlich bleibt und was nicht

- Das Repository bleibt öffentlich (nur dann sind die GitHub-Läufe kostenlos unbegrenzt). Dort liegen der Code,
  die Konfiguration und kleine Zwischenspeicher mit Schlagzeilen und Terminen. Keine Depotdaten, das Depot liegt
  verschlüsselt nur in der Seite selbst.
- Die fertige Seite mit allen Daten liegt nach dem Umzug nur noch bei Cloudflare hinter dem Login.
- Passwörter, Token und Secrets gehören nie in das Repository oder in den Chat.
