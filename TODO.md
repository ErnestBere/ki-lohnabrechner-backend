# KI-Lohnabrechner — TODO

## Offen

- [ ] **Benachrichtigungs-Mails über eigenen SMTP statt Microsoft Graph senden**
  - Aktuell: `Mail.Send` Scope über Microsoft Graph (sendet von Thomas' Mailbox)
  - Ziel: SMTP über Plinius-Mailserver (z.B. `noreply@plinius-systems.de`)
  - Vorteil: `Mail.Send` Scope kann entfernt werden, weniger Berechtigungen auf Thomas' Mailbox
  - Benötigt: SMTP-Host, Port, User, Passwort als Env-Variablen in Cloud Run
  - Betrifft: `send_notification_email()` Funktion in main.py

- [ ] **Vertex AI aktivieren und testen** (DSGVO)
  - Code ist umgestellt (`vertexai=True, location="europe-west3"`)
  - Vertex AI API muss im GCP-Projekt aktiviert werden
  - IAM-Rolle "Vertex AI User" für Service Account vergeben

- [ ] **CDPA (Cloud Data Processing Addendum) akzeptieren**
  - GCP Console → Datenschutz und Sicherheit

- [ ] **AVV mit Kunden abschließen**
  - Grundlage: `AVV_GRUNDLAGE_FUER_ANWALT.md`
  - Anwalt erstellt rechtssicheren AVV

- [ ] **Frontend im Buchhalter-Stil fertigstellen**
  - Login-Screen und Sidebar-Layout sind umgebaut
  - Dashboard, Konfiguration, Mitarbeiter-Seiten prüfen

## Erledigt

- [x] Gesamter Verarbeitungs-Flow (Webhook → Parser → OneDrive → Entwurf → Lexoffice)
- [x] 3-Stufen-Parser (Text → OCR → Gemini)
- [x] Gemini-Vorab-Check (ist es eine Lohnabrechnung?)
- [x] Mitarbeiter-CRUD
- [x] Konfigurationsseite (Mail-Ordner, Filter, Vorlagen, Basispfad)
- [x] Benachrichtigungs-E-Mail konfigurierbar
- [x] Betrags-Extraktion (Brutto/Netto) im Dashboard
- [x] Dateiname im Thomas-Format (JJMMTT_Gehaltsabrechnung_Name.pdf)
- [x] BetaGuard (Passwort-Schutz)
- [x] Duplikat-Schutz
- [x] Fehler-Benachrichtigungen bei allen Edge Cases
- [x] DOKUMENTATION.md
