# Abnahmekriterien — KI-Lohnabrechner
Stand: April 2026

Diese Checkliste definiert alle Bedingungen die vor der Produktivnahme erfüllt sein müssen.
Jeder Punkt wird manuell durch den Auftraggeber (Thomas) oder Plinius getestet.

---

## 1. AUTHENTIFIZIERUNG

- [X ] 1.1 Beta-Passwort-Schutz: Ohne korrektes Passwort ist die App nicht zugänglich
- [X ] 1.2 Microsoft-Login: Klick auf "Login" leitet zu Microsoft-Anmeldung weiter
- [ X] 1.3 Nach erfolgreichem Login landet man auf dem Dashboard
- [ X] 1.4 Abmelden funktioniert und leitet zurück zum Login-Screen
- [ ] 1.5 Nach erneutem Öffnen der App (Browser-Tab) bleibt man eingeloggt (kein erneutes Login nötig)  NICHT erfüllt
- [ X] 1.6 Falsche Microsoft-Zugangsdaten zeigen eine verständliche Fehlermeldung
- [X ] 1.7 Webhook entfernbar
- [ ]  1.8  berechtigungne maximal eingeschrönkt, partnetsatuts microstfot , Vertrag der die nutzung der rechte seintes plinius einschrönkt
---

## 2. KONFIGURATION

- [ X] 2.1 Konfigurationsseite lädt bestehende Einstellungen vor (Pre-fill)
- [X ] 2.2 Mail-Ordner-Dropdown zeigt alle Outlook-Ordner des angemeldeten Kontos
- [X ] 2.3 Steuerbüro-Absender kann gesetzt werden (Pflichtfeld)
- [ X] 2.4 OneDrive-Basispfad kann gesetzt werden
- [X ] 2.5 Fehler-Benachrichtigungs-E-Mail kann gesetzt werden
- [ ] 2.6 Betreff- und Inhalt-Filter können als Tags eingegeben werden (Enter-Taste) to be testes if filter wirklihc funtkionert
- [ X] 2.7 Lexoffice API-Key kann gesetzt werden (wird als *** angezeigt)
- [X ] 2.8 E-Mail-Vorlagen können angepasst werden
- [ ] 2.9 Zahlungs-Tracking kann aktiviert/deaktiviert werden to be testsed
- [ ] 2.10 Speichern löst Microsoft-Autorisierung aus (beim ersten Mal) to be tested
- [ X] 2.11 Nach Speichern erscheint Erfolgsmeldung
- [ ] 2.12 Webhook-Status: Nach Speichern ist der Webhook aktiv (Microsoft sendet Validierungsanfrage) to be tested

---

## 3. MITARBEITER-VERWALTUNG

- [ X] 3.1 Mitarbeiter können angelegt werden (Name, PNr, E-Mail)
- [ X] 3.2 Personalnummer ist eindeutig — doppelte PNr wird abgelehnt
- [X ] 3.3 OneDrive-Ordner ist optional — leer lassen aktiviert Auto-Match
- [X ] 3.4 Mitarbeiter können bearbeitet werden
- [ X] 3.5 Mitarbeiter können gelöscht werden (mit Bestätigungsdialog)
- [ X] 3.6 Mitarbeiterliste wird korrekt angezeigt

---

## 4. HAUPTFLOW — LOHNABRECHNUNG VERARBEITEN

### 4.1 E-Mail-Empfang und Filterung
- [ ] 4.1.1 E-Mail vom konfigurierten Steuerbüro-Absender mit PDF-Anhang wird verarbeitet
- [X ] 4.1.2 E-Mail von einem anderen Absender wird ignoriert (kein Log-Eintrag)
- [ ] 4.1.3 E-Mail ohne PDF-Anhang: Benachrichtigungs-Mail wird gesendet, kein Absturz
- [ ] 4.1.4 PDF die keine Lohnabrechnung ist (z.B. Rechnung): Benachrichtigungs-Mail, kein Absturz
- [ ] 4.1.5 Gleiche E-Mail wird nicht doppelt verarbeitet (Duplikat-Schutz)
- [ ] 4.1.6 Betreff-Filter: E-Mail ohne passenden Betreff wird ignoriert (wenn Filter gesetzt)

### 4.2 PDF-Verarbeitung
- [ ] 4.2.1 Seite 1 (Zahlungsübersicht) wird als "zahlungsuebersicht" erkannt und übersprungen
- [ ] 4.2.2 Lohnabrechnung-Seiten werden als "lohnabrechnung" erkannt
- [ ] 4.2.3 Mitarbeitername wird korrekt extrahiert (Gemini)
- [ ] 4.2.4 Personalnummer wird korrekt extrahiert
- [ ] 4.2.5 Abrechnungsmonat wird korrekt erkannt (z.B. "März 2026")
- [ ] 4.2.6 Brutto-Betrag wird korrekt extrahiert (Gemini-Wert, nicht OCR)
- [ ] 4.2.7 Netto-Betrag wird korrekt extrahiert

### 4.3 Mitarbeiter-Zuordnung
- [ X] 4.3.1 Zuordnung per Personalnummer funktioniert (exakter Match)
- [ X] 4.3.2 Zuordnung per Name funktioniert (Fallback wenn keine PNr)
- [ X] 4.3.3 Nicht zuordenbare Seite landet in `{Basispfad}/_Unklar/` mit MA-Name im Dateinamen
- [ X] 4.3.4 Benachrichtigungs-Mail bei unklaren Seiten wird gesendet  (hier muss noch geändert werden, dass die nachticht nicht von der mail selbst geschigkt wird sondernvom loggin ssytem, damit wr den email write webhook entfenren können)

### 4.4 OneDrive-Ablage
- [ X] 4.4.1 Einzel-PDF wird im manuell konfigurierten Ordner abgelegt
- [X ] 4.4.2 Auto-Match: Wenn kein Ordner konfiguriert, wird passender Unterordner im Basispfad gefunden
- [ X] 4.4.3 Dateiname hat Format: `JJMMTT_Gehaltsabrechnung_Vorname_Nachname.pdf`
- [ X] 4.4.4 Ordner wird automatisch angelegt wenn er nicht existiert
- [ X] 4.4.5 Temporäre Datei in `_TEMP/` wird nach Verarbeitung gelöscht

### 4.5 E-Mail-Entwürfe
- [ X] 4.5.1 Outlook-Entwurf wird für jeden zugeordneten Mitarbeiter erstellt
- [ X] 4.5.2 Entwurf enthält die individuelle PDF als Anhang
- [ X] 4.5.3 Betreff und Text entsprechen den konfigurierten Vorlagen
- [X ] 4.5.4 `{monat}` Platzhalter wird durch den Abrechnungsmonat ersetzt
- [ X] 4.5.5 Entwurf wird NICHT automatisch gesendet

### 4.6 Lexoffice-Upload
- [ ] 4.6.1 PDF wird als Beleg in Lexoffice hochgeladen (wenn API-Key konfiguriert)
- [ ] 4.6.2 Beleg erscheint in Lexoffice unter "Zu prüfen"
- [ ] 4.6.3 Betrag ist korrekt gesetzt (Brutto-Betrag aus der Abrechnung)
- [ ] 4.6.4 Kein Upload wenn kein API-Key konfiguriert (kein Fehler)

---

## 5. DASHBOARD

### 5.1 Anzeige
- [ ] 5.1.1 Logs werden nach Monaten gruppiert angezeigt
- [ ] 5.1.2 Aktueller Monat ist aufgeklappt, ältere Monate eingeklappt
- [ ] 5.1.3 Monats-Header zeigt: Anzahl Verarbeitungen, Gesamt-Brutto, Gesamt-Netto
- [ ] 5.1.4 Log-Karte zeigt: Status-Badge, Dateiname, Timestamp, Erkannt/Fehler/Unklar
- [ ] 5.1.5 Klick auf Log-Karte klappt Details auf/zu
- [ ] 5.1.6 Status-Balken links: grün (Erfolg), gelb (Teilweise), rot (Fehler)

### 5.2 Detail-Ansicht
- [ ] 5.2.1 Zahlungsübersicht zeigt alle Zahlungspositionen (Empfänger, Betrag, Fälligkeit)
- [ ] 5.2.2 Seiten-Tabelle zeigt alle Seiten mit Status, Mitarbeiter, Brutto, Netto
- [ ] 5.2.3 Übersprungene Seiten (Zahlungsübersicht) werden grau angezeigt
- [ ] 5.2.4 Zugeordnete Seiten werden grün angezeigt
- [ ] 5.2.5 Unklare Seiten werden gelb angezeigt

### 5.3 Zahlungs-Tracking (wenn aktiviert)
- [ ] 5.3.1 Checkboxen erscheinen in der Zahlungsübersicht
- [ ] 5.3.2 Checkbox anklicken markiert Position als bezahlt (Zeile wird durchgestrichen)
- [ ] 5.3.3 Status bleibt nach Seiten-Reload erhalten (Firestore-Persistenz)
- [ ] 5.3.4 Wenn Zahlungs-Tracking deaktiviert: keine Checkboxen sichtbar

### 5.4 Log-Verwaltung
- [ ] 5.4.1 Einzelnen Log löschen (✕-Button) funktioniert mit Bestätigungsdialog
- [ ] 5.4.2 "Alle Logs löschen" löscht alle Logs und Duplikat-Schutz
- [ ] 5.4.3 Nach dem Löschen können E-Mails erneut verarbeitet werden

---

## 6. FEHLERBEHANDLUNG

- [ ] 6.1 PDF nicht lesbar: Benachrichtigungs-Mail, Log-Eintrag "error", kein Absturz
- [ ] 6.2 PDF > 25 MB: Benachrichtigungs-Mail, übersprungen
- [ ] 6.3 OneDrive-Upload fehlgeschlagen: Benachrichtigungs-Mail, nächster Mitarbeiter wird trotzdem verarbeitet
- [ ] 6.4 Lexoffice-Upload fehlgeschlagen: Geloggt, Pipeline läuft weiter
- [ ] 6.5 Microsoft Token abgelaufen: `auth_status = disconnected` in Firestore, Warnung im Frontend
- [ ] 6.6 Gemini nicht verfügbar: Fallback auf OCR/Text, Pipeline läuft weiter
- [ ] 6.7 Alle Fehler-Mails gehen an die konfigurierte Benachrichtigungs-E-Mail

---

## 7. SICHERHEIT

- [ ] 7.1 Ohne Login ist keine Seite der App zugänglich
- [ ] 7.2 Tenant-Isolation: Kunde A sieht keine Daten von Kunde B
- [ ] 7.3 Lexoffice API-Key wird verschlüsselt gespeichert (nicht im Klartext in Firestore)
- [ ] 7.4 Microsoft Refresh Token wird verschlüsselt gespeichert
- [ ] 7.5 Webhook-Validierung: Gefälschte Webhook-Aufrufe werden abgelehnt

---

## 8. PERFORMANCE & STABILITÄT

- [ ] 8.1 Verarbeitung einer 5-seitigen PDF dauert unter 3 Minuten
- [ ] 8.2 Dashboard lädt in unter 3 Sekunden
- [ ] 8.3 Mehrfache gleichzeitige Webhook-Aufrufe (Microsoft sendet oft mehrfach) werden korrekt dedupliziert
- [ ] 8.4 Cloud Run startet nach Idle-Timeout korrekt neu

---

## 9. DATENSCHUTZ (vor Produktivnahme)

- [ ] 9.1 Google Cloud CDPA ist akzeptiert (GCP Console → Datenschutz)
- [ ] 9.2 Vertex AI API ist aktiviert (Daten bleiben in Frankfurt)
- [ ] 9.3 AVV zwischen Plinius und Kunde ist unterzeichnet
- [ ] 9.4 Mitarbeiter des Kunden sind über Cloud-Verarbeitung informiert
- [ ] 9.5 DSFA (Datenschutz-Folgenabschätzung) ist erstellt

---

## ABNAHME-SIGNATUR

| Punkt | Getestet von | Datum | Ergebnis |
|---|---|---|---|
| 1-3 (Auth, Konfig, MA) | | | |
| 4 (Hauptflow) | | | |
| 5 (Dashboard) | | | |
| 6 (Fehlerbehandlung) | | | |
| 7-8 (Sicherheit, Performance) | | | |
| 9 (Datenschutz) | | | |

**Freigabe zur Produktivnahme:** _____________________ Datum: _____________



Verwalten Sie den Zugriff auf Daten, für die Sie Lohnabrechner-Webhook Zugriff erteilt haben.
Ermöglicht Lohnabrechner-Webhook das Anzeigen und Aktualisieren der Daten, auf die Sie Zugriff erteilt haben, selbst wenn Sie die App zurzeit nicht verwenden. Lohnabrechner-Webhook werden hierdurch keine zusätzlichen Berechtigungen gewährt.

Lesen Ihres Profils
Lohnabrechner-Webhook kann Ihr Profil lesen.

Lesen Ihrer E-Mails
Lohnabrechner-Webhook kann E-Mails in Ihrem Postfach lesen.

Lese- und Schreibzugriff auf Ihre E-Mails
Lohnabrechner-Webhook kann E-Mails in Ihrem Postfach lesen, aktualisieren, erstellen und löschen. Eine Berechtigung zum Senden von E-Mails ist nicht enthalten.

Vollzugriff auf alle Dateien, auf die Sie Zugriff haben
Lohnabrechner-Webhook kann alle OneDrive-Dateien lesen, erstellen, aktualisieren und löschen, auf die Sie zugreifen können.