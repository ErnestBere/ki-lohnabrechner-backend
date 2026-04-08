# KI-Lohnabrechner — Technische Dokumentation

> Version: 1.0 | Stand: April 2026 | Projekt: ki-lohnabrechner


---

## Inhaltsverzeichnis

1. [Projektübersicht](#1-projektübersicht)
2. [Systemarchitektur](#2-systemarchitektur)
3. [Authentifizierung und Sicherheit](#3-authentifizierung-und-sicherheit)
4. [Datenmodell und Firestore-Struktur](#4-datenmodell-und-firestore-struktur)
5. [Backend — API-Endpunkte](#5-backend--api-endpunkte)
6. [Verarbeitungspipeline (Kern des Systems)](#6-verarbeitungspipeline-kern-des-systems)
7. [PDF-Parser: 3-Stufen-Pipeline](#7-pdf-parser-3-stufen-pipeline)
8. [Microsoft Graph API Integration](#8-microsoft-graph-api-integration)
9. [Lexoffice Integration](#9-lexoffice-integration)
10. [Frontend — Seiten und Komponenten](#10-frontend--seiten-und-komponenten)
11. [Konfigurationsparameter](#11-konfigurationsparameter)
12. [Fehlerbehandlung und Benachrichtigungen](#12-fehlerbehandlung-und-benachrichtigungen)
13. [Deployment](#13-deployment)
14. [Umgebungsvariablen](#14-umgebungsvariablen)

---

## 1. Projektübersicht

Der **KI-Lohnabrechner** ist ein vollautomatisches System zur Verarbeitung von monatlichen Gehaltsabrechnungs-PDFs. Das Steuerbüro schickt jeden Monat eine einzige Sammel-PDF per E-Mail an den Kunden (z.B. Thomas von "projektwärts"). Diese PDF enthält auf Seite 1 eine Zahlungsübersicht und auf den Folgeseiten die individuellen Lohnabrechnungen aller Mitarbeiter.

Das System:
- erkennt die eingehende E-Mail automatisch per Microsoft 365 Webhook
- zerlegt die Sammel-PDF seitenweise
- erkennt pro Seite den Mitarbeiternamen und die Personalnummer (3-Stufen-Parser)
- ordnet jede Seite einem Mitarbeiter aus den Stammdaten zu
- erzeugt individuelle Einzel-PDFs pro Mitarbeiter
- legt die PDFs in OneDrive im richtigen Mitarbeiterordner ab
- erstellt E-Mail-Entwürfe in Outlook (nicht gesendet — Thomas prüft und sendet manuell)
- lädt die PDFs optional in Lexoffice hoch
- benachrichtigt Thomas bei Fehlern oder nicht zuordenbaren Seiten

### Technologie-Stack

| Schicht | Technologie |
|---|---|
| Backend | Python 3.11, FastAPI, uvicorn |
| Hosting Backend | Google Cloud Run (europe-west3) |
| Datenbank | Google Firestore (Datenbank: "lohnabrechner") |
| Auth Backend | Firebase Admin SDK (Custom Tokens) |
| Auth Frontend | Microsoft MSAL (Azure AD, Multitenant) |
| PDF-Verarbeitung | PyMuPDF (fitz), Tesseract OCR, Gemini Vision |
| KI-Validierung | Google Gemini API (gemini-3.1-pro-preview) |
| Microsoft-Integration | Microsoft Graph API v1.0 |
| Buchhaltung | Lexoffice REST API |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS |
| Hosting Frontend | Cloudflare Pages |
| Verschlüsselung | Fernet (AES-128-CBC, cryptography-Bibliothek) |
| Rate Limiting | slowapi |

---

## 2. Systemarchitektur

### Überblick

`
[Steuerbüro]
     |
     | E-Mail mit Sammel-PDF
     v
[Microsoft 365 Postfach von Thomas]
     |
     | Graph API Webhook (POST /webhook/m365)
     v
[Cloud Run Backend — ki-lohnabrechner-backend]
     |
     |-- PDF-Parser (PyMuPDF + Tesseract + Gemini)
     |-- Mitarbeiter-Zuordnung (Firestore Stammdaten)
     |-- Einzel-PDFs erzeugen (PyMuPDF)
     |
     |-- OneDrive Upload (Graph API)
     |-- E-Mail-Entwurf erstellen (Graph API)
     |-- Lexoffice Upload (Lexoffice API)
     |-- Log schreiben (Firestore)
     |
     v
[Firestore — lohnabrechner DB]
     |
     | onSnapshot (Echtzeit)
     v
[Cloudflare Pages Frontend — ki-lohnabrechner-frontend]
     |
     | Dashboard zeigt Logs in Echtzeit
     v
[Thomas im Browser]
`

### Repo-Struktur

`
ki-lohnabrechner-backend/
  main.py              # Gesamter Backend-Code (FastAPI App + Pipeline)
  requirements.txt     # Python-Abhängigkeiten
  Dockerfile           # Container-Definition (Python 3.11 + Tesseract)
  .env                 # Lokale Umgebungsvariablen (nicht im Git)
  DOKUMENTATION.md     # Diese Datei

ki-lohnabrechner-frontend/
  src/
    pages/
      DashboardPage.tsx       # Echtzeit-Logs und Verarbeitungsübersicht
      ConfigurationPage.tsx   # Konfigurationsformular
      MitarbeiterPage.tsx     # Mitarbeiter-Stammdaten CRUD
    hooks/
      useAuth.ts              # MSAL + Firebase Auth
      useCustomerConfig.ts    # Konfiguration aus Firestore laden
      useRegistration.ts      # POST /api/register
      useGraphAPI.ts          # Mail-Ordner aus Graph API laden
    config/
      msalConfig.ts           # Azure AD Konfiguration
      firebaseConfig.ts       # Firebase/Firestore Konfiguration
  package.json
  vite.config.ts
`

---

## 3. Authentifizierung und Sicherheit

### Auth-Flow (Schritt für Schritt)

`
1. Thomas öffnet das Frontend (Cloudflare Pages)
2. Klick auf "Mit Microsoft anmelden"
3. MSAL leitet zu Azure AD weiter (loginRedirect)
4. Thomas autorisiert die App (Scopes: User.Read, Mail.Read, Mail.ReadWrite, Files.ReadWrite.All, offline_access)
5. Azure AD leitet zurück zum Frontend mit Access Token
6. Frontend sendet Access Token an Backend: POST /api/auth/firebase
7. Backend verifiziert Token bei Microsoft Graph (/me)
8. Backend erstellt Firebase Custom Token (mit tid-Claim = Azure Tenant ID)
9. Frontend meldet sich mit Custom Token bei Firebase an (signInWithCustomToken)
10. Firebase gibt JWT zurück — dieser wird für alle weiteren API-Calls genutzt
`

### Microsoft OAuth2 für Webhook-Setup

Beim ersten Speichern der Konfiguration (POST /api/register) hat das Backend noch keinen Refresh Token. Ablauf:

`
1. POST /api/register → Backend hat keinen Refresh Token
2. Backend generiert Microsoft Auth URL (MSAL Authorization Code Flow)
3. Frontend leitet Thomas zu Microsoft weiter
4. Thomas autorisiert → Microsoft leitet zu GET /api/auth/callback zurück
5. Backend tauscht Authorization Code gegen Access Token + Refresh Token
6. Refresh Token wird verschlüsselt in Firestore gespeichert
7. Backend richtet M365 Webhook ein
8. Redirect zurück zum Frontend Dashboard
`

### Token-Verwaltung

- **Access Token**: Kurzlebig (1h), wird bei jedem Webhook-Aufruf frisch geholt
- **Refresh Token**: Langlebig, verschlüsselt mit Fernet (AES) in Firestore gespeichert
- **Firebase JWT**: Kurzlebig (1h), wird vom Frontend für alle Backend-Calls genutzt
- **Webhook clientState**: Zufälliger 64-Zeichen Hex-String, verhindert gefälschte Webhook-Aufrufe

### Sicherheitsmaßnahmen

| Maßnahme | Implementierung |
|---|---|
| Firebase JWT Verifikation | erify_firebase_token() auf allen geschützten Endpunkten |
| Tenant-Isolation | Jeder User sieht nur seine eigenen Daten (tenant_id Check) |
| Refresh Token Verschlüsselung | Fernet AES-128-CBC, Key aus Umgebungsvariable |
| Lexoffice API-Key Verschlüsselung | Ebenfalls Fernet, nur verschlüsselt in Firestore |
| Webhook clientState Validierung | Verhindert gefälschte Webhook-Aufrufe von Dritten |
| Duplikat-Schutz | Message-ID in lohn_processed_mails Collection |
| Rate Limiting | slowapi, IP-basiert (X-Forwarded-For aware für Cloud Run) |
| Cron API-Key | BACKEND_API_SECRET Header für /api/cron/renew |
| Firestore Security Rules | Frontend darf nur lesen, Backend (Admin SDK) schreibt |

### Firestore Security Rules

`javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    function belongsToTenant(tenantId) {
      return request.auth != null &&
        (request.auth.token.tid == tenantId || request.auth.uid == tenantId);
    }
    match /lohn_kunden/{tenantId} {
      allow get: if belongsToTenant(tenantId);
      allow list: if false;
      allow write: if false;  // Nur Backend (Admin SDK)
      match /postfaecher/{email} {
        allow read: if belongsToTenant(tenantId);
        allow write: if false;
      }
      match /mitarbeiter/{maId} {
        allow read: if belongsToTenant(tenantId);
        allow list: if belongsToTenant(tenantId);
        allow write: if false;
      }
      match /verarbeitungs_logs/{logId} {
        allow read: if belongsToTenant(tenantId);
        allow list: if belongsToTenant(tenantId);
        allow write: if false;
      }
    }
    match /lohn_processed_mails/{document=**} {
      allow read, write: if false;
    }
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
`

---

## 4. Datenmodell und Firestore-Struktur

### Datenbank: "lohnabrechner"

`
lohn_kunden/
  {tenant_id}/                          # Azure AD Tenant ID des Kunden
    firmen_name: string                 # z.B. "projektwärts"
    steuerbuero_absender: string        # E-Mail des Steuerbüros (Filter)
    onedrive_basispfad: string          # z.B. "Personal"
    email_betreff_vorlage: string       # z.B. "Ihre Gehaltsabrechnung {monat}"
    email_text_vorlage: string          # Vorlagentext für E-Mail-Entwürfe
    filter_betreff: string[]            # Optionale Betreff-Filter
    filter_inhalt: string[]             # Optionale Inhalt-Filter
    benachrichtigungs_email: string     # Empfänger für Fehler-Mails
    lexoffice_api_key: string           # Verschlüsselt (Fernet)

    postfaecher/
      {mailbox_email}/                  # E-Mail-Adresse der überwachten Mailbox
        tenant_id: string
        mailbox_email: string
        ziel_ordner: string             # Folder-ID oder leer (alle Ordner)
        m365_refresh_token: string      # Verschlüsselt (Fernet)
        subscription_id: string         # Microsoft Graph Webhook-ID
        client_state: string            # Webhook-Sicherheitstoken (64 Hex-Zeichen)
        auth_status: string             # "connected" | "disconnected"
        auth_error: string | null       # Fehlermeldung bei Disconnect

    mitarbeiter/
      {auto_id}/                        # Automatisch generierte Firestore-ID
        name: string                    # Vollständiger Name, z.B. "Maximilian Schmidt"
        personal_nr: string             # z.B. "00001"
        email: string                   # E-Mail für Entwurf-Empfänger
        onedrive_ordner: string         # z.B. "Personal/Maximilian_Schmidt"
        erstellt_am: timestamp

    verarbeitungs_logs/
      {auto_id}/                        # Ein Eintrag pro verarbeiteter PDF
        timestamp: timestamp
        status: string                  # "success" | "error" | "partial"
        dateiname: string               # Originaldateiname der Sammel-PDF
        gesamt_seiten: number
        erkannte_mitarbeiter: number
        fehler_anzahl: number
        nicht_zugeordnet: number
        message: string                 # Zusammenfassung
        seiten_details: array           # Details pro Seite (siehe unten)

lohn_processed_mails/
  {message_id}/                         # Microsoft Message-ID (Duplikat-Schutz)
    status: string                      # "processing" | "done"
    received_at: timestamp
    processed_at: timestamp
`

### seiten_details Struktur (pro Seite im Log)

`json
{
  "seite": 2,
  "typ": "lohnabrechnung",
  "mitarbeiter_name": "Maximilian Schmidt",
  "personal_nr": "00001",
  "status": "zugeordnet",
  "quelle": "text+gemini",
  "validierung": "match",
  "fehler_details": null
}
`

**Status-Werte:**
- zugeordnet — Mitarbeiter in Stammdaten gefunden, PDF verarbeitet
- unklar — Mitarbeiter nicht in Stammdaten, PDF in _Unklar abgelegt
- uebersprungen — Seite ist keine Lohnabrechnung (z.B. Zahlungsübersicht)
- ehler — Technischer Fehler bei der Verarbeitung

**Quelle-Werte:**
- 	ext — Direkt aus PDF-Textlayer extrahiert
- ocr — Per Tesseract OCR aus Bild extrahiert
- 	ext+gemini — Textlayer + Gemini-Validierung
- ocr+gemini — OCR + Gemini-Validierung

**Validierung-Werte:**
- match — Text/OCR und Gemini stimmen überein
- korrigiert — Gemini hat einen anderen Namen erkannt (Gemini-Wert wird verwendet)
- 
ur_gemini — Nur Gemini hat den Namen erkannt (Text/OCR hat versagt)
- 
ur_lokal — Nur Text/OCR hat erkannt, Gemini hat nichts gefunden
- 
icht_erkannt — Weder Text/OCR noch Gemini haben etwas erkannt
- ehler — Gemini-API-Fehler

---

## 5. Backend — API-Endpunkte

### Öffentliche Endpunkte (kein Auth)

#### GET /
Health Check. Gibt zurück ob Server, Firestore und Gemini verfügbar sind.
`json
{"status": "ok", "service": "ki-lohnabrechner-backend", "db": true, "gemini": true}
`

#### POST /api/auth/firebase
Tauscht einen Microsoft Access Token gegen einen Firebase Custom Token.

**Request:**
`json
{"access_token": "eyJ...", "tenant_id": "21..."}
`

**Ablauf:**
1. Verifiziert den MS Access Token bei https://graph.microsoft.com/v1.0/me
2. Extrahiert die Microsoft User-ID
3. Erstellt Firebase Custom Token mit 	id-Claim (Azure Tenant ID)
4. Gibt den Firebase Token zurück

**Response:**
`json
{"firebase_token": "eyJ..."}
`

#### GET /api/auth/callback
OAuth2 Callback nach Microsoft-Login. Empfängt Authorization Code, tauscht ihn gegen Tokens, speichert Refresh Token verschlüsselt in Firestore, richtet Webhook ein.

**Query-Parameter:** code, state (Base64-kodiertes JSON mit tenant_id und mailbox_email)

**Redirect:** Nach Erfolg zu {FRONTEND_URL}/dashboard?success=true

#### POST /webhook/m365
Microsoft Graph Webhook-Empfänger. Wird von Microsoft aufgerufen wenn eine neue E-Mail mit Anhang eingeht.

**Validation:** Bei ?validationToken=... gibt der Endpunkt den Token zurück (Webhook-Registrierung).

**Verarbeitung:** Startet die Verarbeitungspipeline asynchron. Gibt sofort 202 zurück.

### Geschützte Endpunkte (Firebase JWT erforderlich)

#### POST /api/register
Speichert die Kundenkonfiguration und richtet den M365 Webhook ein.

**Request:** LohnKundenProfil (siehe Datenmodell)

**Ablauf:**
1. Prüft Firebase JWT und Tenant-Berechtigung
2. Speichert Konfiguration in lohn_kunden/{tenant_id}
3. Speichert Postfach-Daten in lohn_kunden/{tenant_id}/postfaecher/{email}
4. Verschlüsselt und speichert Lexoffice API-Key falls angegeben
5. Versucht Webhook mit vorhandenem Refresh Token einzurichten
6. Falls kein Token: Gibt Microsoft Auth URL zurück (status: "auth_required")

**Response (Erfolg):**
`json
{"status": "success", "message": "Konfiguration erfolgreich gespeichert!"}
`

**Response (Auth nötig):**
`json
{"status": "auth_required", "auth_url": "https://login.microsoftonline.com/..."}
`

#### GET /api/mitarbeiter
Gibt alle Mitarbeiter des authentifizierten Tenants zurück.

#### POST /api/mitarbeiter
Legt einen neuen Mitarbeiter an. Prüft Eindeutigkeit der Personalnummer.

**Request:**
`json
{"name": "Maximilian Schmidt", "personal_nr": "00001", "email": "max@example.de", "onedrive_ordner": "Personal/Maximilian_Schmidt"}
`

#### PUT /api/mitarbeiter/{ma_id}
Aktualisiert einen Mitarbeiter. Prüft PNr-Eindeutigkeit (außer bei sich selbst).

#### DELETE /api/mitarbeiter/{ma_id}
Löscht einen Mitarbeiter.

#### DELETE /api/webhook/{tenant_id}/{mailbox_email}
Löscht den Webhook bei Microsoft und entfernt das Postfach aus Firestore.

### Server-zu-Server Endpunkte (API-Key erforderlich)

#### GET /api/cron/renew
Verlängert alle aktiven Webhooks (Microsoft Subscriptions laufen nach 2 Tagen ab). Wird täglich von einem Cloud Scheduler aufgerufen.

**Header:** x-api-key: {BACKEND_API_SECRET}

**Response:**
`json
{"renewed": 3, "errors": 0}
`

---

## 6. Verarbeitungspipeline (Kern des Systems)

Die Funktion process_sammel_pdf() ist das Herzstück des Systems. Sie wird asynchron vom Webhook-Endpunkt aufgerufen.

### Vollständiger Ablauf

`
E-Mail eingetroffen (Webhook)
│
├── Duplikat-Prüfung (Message-ID in lohn_processed_mails)
│   └── Bereits verarbeitet → Abbruch
│
├── Postfach-Lookup (subscription_id → Firestore)
│   └── Nicht gefunden → Abbruch
│
├── clientState-Validierung (Sicherheitscheck)
│   └── Falsch → Abbruch (Sicherheitswarnung)
│
├── Tenant-Daten laden (Konfiguration aus Firestore)
│
├── M365 Access Token holen (Refresh Token → MSAL)
│   └── Token abgelaufen → auth_status = "disconnected", Abbruch
│
├── E-Mail-Metadaten laden (Absender, Betreff, Body)
│   ├── Absender-Filter: Nicht vom Steuerbüro → Überspringen
│   ├── Betreff-Filter: Kein Match → Überspringen
│   └── Inhalt-Filter: Kein Match → Überspringen
│
├── PDF-Anhänge prüfen
│   ├── Kein PDF → Info-Mail an Thomas, Abbruch
│   └── PDF > 25 MB → Überspringen
│
├── PDF herunterladen (Graph API)
│
├── Sammel-PDF temporär in OneDrive speichern (_TEMP/)
│
├── Mitarbeiter-Stammdaten aus Firestore laden
│
├── Seiten verarbeiten (3-Stufen-Parser, pro Seite)
│   ├── Stufe 1: Text-Layer (PyMuPDF)
│   ├── Stufe 2: OCR (Tesseract, nur wenn kein Text)
│   └── Stufe 3: Gemini Vision (immer, zur Validierung)
│
├── Seiten nach Mitarbeiter gruppieren
│   ├── Zuordnung per Personalnummer (exakter Match)
│   ├── Zuordnung per Name (Fallback)
│   └── Nicht zuordenbar → PDF in _Unklar/, Info-Mail an Thomas
│
├── Pro Mitarbeiter:
│   ├── Einzel-PDF erzeugen (PyMuPDF)
│   ├── Dateiname: Gehaltsabrechnung_<Name>_<MM-YYYY>.pdf
│   ├── OneDrive: Ordner prüfen/anlegen, PDF hochladen
│   ├── E-Mail-Entwurf erstellen (Outlook, nicht senden)
│   └── Lexoffice Upload (falls API-Key konfiguriert)
│
├── Temp-Datei aus OneDrive löschen
│
└── Verarbeitungs-Log in Firestore schreiben
`

### Mitarbeiter-Zuordnung (match_mitarbeiter)

Die Zuordnung läuft in zwei Stufen:

1. **Personalnummer (primär):** Exakter String-Vergleich. "00001" == "00001". Wichtig: Die Personalnummer muss exakt so eingetragen sein wie sie in der PDF steht (mit führenden Nullen).

2. **Name (Fallback):** Case-insensitiver Vergleich. "maximilian schmidt" == "maximilian schmidt". Wird nur genutzt wenn keine Personalnummer erkannt wurde.

### Dateiname-Generierung (generate_filename)

`
Gehaltsabrechnung_<Name>_<MM-YYYY>.pdf

Beispiele:
  Gehaltsabrechnung_Maximilian_Schmidt_03-2026.pdf
  Gehaltsabrechnung_Hannah_Meyer_03-2026.pdf
`

Monatsmapping: "März" → "03", "April" → "04", etc.

### OneDrive-Ordnerstruktur

`
{onedrive_basispfad}/           z.B. "Personal"
  _TEMP/                        Temporäre Ablage der Sammel-PDF (wird nach Verarbeitung gelöscht)
  _Unklar/                      Nicht zuordenbare Seiten
    Unklar_Jonas_Becker_Seite_4_Lohnauswertungen_März_2026.pdf
  Maximilian_Schmidt/           Mitarbeiter-Ordner (automatisch angelegt)
    Gehaltsabrechnungen/
      Gehaltsabrechnung_Maximilian_Schmidt_03-2026.pdf
  Hannah_Meyer/
    Gehaltsabrechnungen/
      Gehaltsabrechnung_Hannah_Meyer_03-2026.pdf
`

Der Ordnerpfad pro Mitarbeiter kann in den Stammdaten individuell überschrieben werden (Feld onedrive_ordner). Standard ist {basispfad}/{Name_mit_Unterstrichen}.

---

## 7. PDF-Parser: 3-Stufen-Pipeline

Der Parser ist das technisch komplexeste Modul. Er muss zuverlässig mit verschiedenen PDF-Typen umgehen: textbasierte PDFs (direkt vom DATEV-System), bildbasierte PDFs (gescannt) und gemischte PDFs (teilweise geschwärzt).

### Stufe 1: Text-Layer Extraktion (extract_from_text)

PyMuPDF extrahiert den eingebetteten Text direkt aus der PDF. Kein OCR, sehr schnell.

**Erkennung Zahlungsübersicht:**
- Keywords: "Übersicht Zahlungen", "Zahlungen im"
- Seite wird als zahlungsuebersicht klassifiziert und übersprungen

**Erkennung Lohnabrechnung:**
- Keywords: "Abrechnung der Brutto", "Brutto/Netto", "Pers.-Nr.", "NETTO-VERDIENST", etc.

**Personalnummer-Extraktion (Regex):**
`python
r"\*?Pers\.?\s*-?\s*Nr\.?\s*(\d{3,})\*?"
r"Personal\s*-?\s*Nr\.?\s*(\d{3,})"
`

**Namens-Extraktion:**
Der Name steht in DATEV-Abrechnungen typischerweise nach der Personalnummer-Zeile und vor der Firmenadresse. Der Parser sucht nach einer Zeile die:
- Mindestens 2 Wörter hat
- Nur Buchstaben, Leerzeichen, Bindestriche enthält
- Keine DATEV-Keywords enthält (Brutto, Netto, Steuer, etc.)

### Stufe 2: OCR (extract_from_ocr)

Wird nur ausgeführt wenn Stufe 1 keinen Text gefunden hat (bildbasierte PDF-Seite).

- Rendert die Seite mit 300 DPI als PNG (PyMuPDF get_pixmap)
- Führt Tesseract OCR mit deutschem Sprachpaket (lang="deu") aus
- Gleiche Regex-Patterns wie Stufe 1, aber mit OCR-Artefakt-Toleranz

**OCR-spezifische Regex für Personalnummer:**
`python
r"\*?Pers\.?\s*[\-—]?\s*Nr\.?\s*(\d{3,})\*?"
r"[Pp]ers\s*[\._\-]\s*[NnXx]r\.?\s*(\d{3,})"
`

**OCR-spezifische Namens-Extraktion:**
OCR liest Name und Personalnummer oft in einer Zeile zusammen (z.B. "Maximilian Schmidt *Pers.-Nr. 00001*"). Der Parser extrahiert den Teil vor der Personalnummer-Angabe und bereinigt OCR-Artefakte.

### Stufe 3: Gemini Vision Validierung (validate_with_gemini)

Läuft **immer** — unabhängig davon ob Stufe 1 oder 2 erfolgreich war. Dient als Sicherheitsnetz und Qualitätskontrolle.

**Prompt:**
`
System: "Du bist ein Experte für deutsche DATEV-Lohnabrechnungen. Extrahiere präzise: 
Mitarbeitername, Personalnummer, Abrechnungsmonat. Bei geschwärzten Feldern: Null. 
Antworte NUR mit JSON."

User: "Analysiere Seite {n} dieser Lohnabrechnung. Extrahiere Mitarbeitername, 
Personalnummer und Abrechnungsmonat."
`

**Response-Schema (Pydantic):**
`python
class GeminiSeitenInfo(BaseModel):
    ist_lohnabrechnung: bool
    mitarbeiter_name: Optional[str]
    personal_nr: Optional[str]
    abrechnungsmonat: Optional[str]
    seitentyp: str  # lohnabrechnung | zahlungsuebersicht | sv_nachweis | sonstiges
`

**Kosten:** ca. .0008 pro Seite (A4 bei 300 DPI ≈ 20 Tiles × 258 Tokens × .15/1M)

### Ergebnis-Zusammenführung (process_page)

Nach allen drei Stufen werden die Ergebnisse zusammengeführt:

| Situation | Ergebnis | Validierung |
|---|---|---|
| Text = Gemini | Text-Wert | match |
| Text ≠ Gemini | Gemini-Wert (bevorzugt) | korrigiert |
| Nur Gemini hat Ergebnis | Gemini-Wert | 
ur_gemini |
| Nur Text hat Ergebnis | Text-Wert | 
ur_lokal |
| Keiner hat Ergebnis | null | 
icht_erkannt |
| Gemini-API-Fehler | Text/OCR-Wert | ehler |

Für die Personalnummer gilt: Bei Widerspruch zwischen Text/OCR und Gemini wird Gemini bevorzugt.

---

## 8. Microsoft Graph API Integration

### Verwendete Scopes

| Scope | Zweck |
|---|---|
| User.Read | Benutzerinfo beim Login abrufen |
| Mail.Read | E-Mails und Anhänge lesen |
| Mail.ReadWrite | E-Mail-Entwürfe erstellen, Benachrichtigungen senden |
| Files.ReadWrite.All | OneDrive-Ordner anlegen, Dateien hochladen/löschen |
| offline_access | Refresh Token für Hintergrundverarbeitung |

### Webhook-Registrierung

Microsoft Graph Webhooks laufen nach maximal 2 Tagen ab und müssen verlängert werden.

**Registrierung (POST /v1.0/subscriptions):**
`json
{
  "changeType": "created",
  "notificationUrl": "https://ki-lohnabrechner-backend.../webhook/m365",
  "resource": "users/{email}/messages?=hasAttachments eq true",
  "expirationDateTime": "2026-04-09T21:03:18Z",
  "clientState": "a3f8b2c1..."
}
`

Mit Ordner-Filter:
`
users/{email}/mailFolders('{folder_id}')/messages?=hasAttachments eq true
`

**Verlängerung (PATCH /v1.0/subscriptions/{id}):**
Täglich per Cloud Scheduler (GET /api/cron/renew).

### OneDrive-Operationen

**Ordner prüfen/anlegen:**
`
GET /v1.0/users/{email}/drive/root:/{pfad}
POST /v1.0/users/{email}/drive/root:/{parent}:/children
  Body: {"name": "Ordnername", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
`

**Datei hochladen:**
`
PUT /v1.0/users/{email}/drive/root:/{pfad}/{dateiname}:/content
Content-Type: application/pdf
Body: [PDF-Bytes]
`

**Datei löschen:**
`
DELETE /v1.0/users/{email}/drive/root:/{pfad}
`

### E-Mail-Entwurf erstellen

`
POST /v1.0/users/{email}/messages
Content-Type: application/json
Body: {
  "subject": "Ihre Gehaltsabrechnung März 2026",
  "body": {"contentType": "HTML", "content": "Anbei..."},
  "toRecipients": [{"emailAddress": {"address": "mitarbeiter@example.de"}}],
  "attachments": [{
    "@odata.type": "#microsoft.graph.fileAttachment",
    "name": "Gehaltsabrechnung_Max_Schmidt_03-2026.pdf",
    "contentType": "application/pdf",
    "contentBytes": "JVBERi0x..."
  }]
}
`

Der Entwurf wird **nicht gesendet** — er liegt in Thomas' Outlook-Entwürfen. Thomas prüft und sendet manuell.

### Benachrichtigungs-Mail senden

`
POST /v1.0/users/{mailbox_email}/sendMail
Body: {
  "message": {
    "subject": "[KI-Lohnabrechner] 2 Abrechnungen nicht zugeordnet",
    "body": {"contentType": "HTML", "content": "..."},
    "toRecipients": [{"emailAddress": {"address": "{benachrichtigungs_email}"}}]
  },
  "saveToSentItems": true
}
`

Die Mail wird **von Thomas' Mailbox** gesendet (Delegated Permission). Der Empfänger ist die konfigurierte enachrichtigungs_email (Standard: Thomas' eigene Adresse).

---

## 9. Lexoffice Integration

### Upload-Endpunkt

`
POST https://api.lexoffice.io/v1/files
Authorization: Bearer {lexoffice_api_key}
Content-Type: multipart/form-data

file: [PDF-Bytes]
type: voucher
`

**Response (202 Accepted):**
`json
{"id": "abc123..."}
`

### Verhalten

- Wird nur ausgeführt wenn ein Lexoffice API-Key konfiguriert ist
- Bei HTTP 429 (Rate Limit): 3 Sekunden warten, bis zu 3 Versuche
- Bei anderen Fehlern: Fehler wird geloggt, Pipeline läuft weiter (nicht kritisch)
- Der Upload-Typ oucher ist aktuell gesetzt — kann bei Bedarf auf sonstige geändert werden

### API-Key Verwaltung

Der Lexoffice API-Key wird verschlüsselt (Fernet) in Firestore gespeichert. Im Frontend wird er als ******** angezeigt wenn bereits ein Key vorhanden ist. Beim Speichern der Konfiguration wird ******** ignoriert (vorhandener Key bleibt erhalten).

---

## 10. Frontend — Seiten und Komponenten

### Seiten

#### Dashboard (/dashboard)
Zeigt die letzten 20 Verarbeitungs-Logs in Echtzeit (Firestore onSnapshot).

Pro Log-Eintrag:
- Status-Badge (Erfolg / Fehler / Teilweise)
- Dateiname der Sammel-PDF
- Zeitstempel der Verarbeitung
- Zusammenfassung (X erkannt, Y Fehler, Z unklar)
- Aufklappbare Detailtabelle mit allen Seiten (Typ, Mitarbeiter, Status, Quelle)

#### Konfiguration (/configuration)
Formular zur Einrichtung und Anpassung der Systemkonfiguration.

Felder:
- **Unternehmen** (read-only, aus Microsoft-Login)
- **Mail-Ordner** (Dropdown, live aus Graph API geladen, optional)
- **Steuerbüro-Absender** (Pflichtfeld, E-Mail-Adresse)
- **Fehler-Benachrichtigung** (optional, Standard: eigene Mailbox)
- **E-Mail Filter** (Tag-Input für Betreff- und Inhalt-Filter)
- **OneDrive Basispfad** (mit Vorschau der Ordnerstruktur)
- **Erweiterte Einstellungen** (aufklappbar):
  - Lexoffice API-Key (mit Show/Hide Toggle)
  - E-Mail Betreff-Vorlage
  - E-Mail Text-Vorlage

Beim Speichern: POST /api/register. Falls Microsoft-Auth nötig: Redirect zu Microsoft Login.

#### Mitarbeiter (/mitarbeiter)
CRUD-Verwaltung der Mitarbeiter-Stammdaten.

Felder pro Mitarbeiter:
- Name (Pflicht)
- Personalnummer (Pflicht, eindeutig)
- E-Mail (Pflicht, für Entwurf-Empfänger)
- OneDrive-Ordner (optional, Standard wird automatisch generiert)

### Hooks

#### useAuth
Verwaltet den gesamten Auth-Zustand.

`	ypescript
const { isAuthenticated, user, login, logout, error, isInitializing } = useAuth();
`

- user.tenantId — Azure AD Tenant ID
- user.email — E-Mail-Adresse
- user.companyName — Firmenname aus Azure AD

Ablauf: MSAL acquireTokenSilent → POST /api/auth/firebase → signInWithCustomToken

#### useCustomerConfig
Lädt die bestehende Konfiguration aus Firestore (für Pre-fill des Formulars).

`	ypescript
const { config, loading, exists } = useCustomerConfig();
`

Liest aus: lohn_kunden/{tenantId} + lohn_kunden/{tenantId}/postfaecher/{email}

#### useRegistration
Sendet die Konfiguration an das Backend.

`	ypescript
const { register, loading, error, success } = useRegistration();
const result = await register(profile);
if (result?.status === 'auth_required') window.location.href = result.auth_url;
`

#### useGraphAPI
Lädt Mail-Ordner aus der Microsoft Graph API (für das Dropdown).

`	ypescript
const { fetchMailFolders } = useGraphAPI();
const folders = await fetchMailFolders(user.email);
`

Filtert System-Ordner (Entwürfe, Gesendete, Papierkorb, etc.) heraus.

---

## 11. Konfigurationsparameter

Alle Parameter werden über das Frontend konfiguriert und in Firestore gespeichert.

| Parameter | Pflicht | Standard | Beschreibung |
|---|---|---|---|
| steuerbuero_absender | Ja | — | E-Mail-Adresse des Steuerbüros. Nur E-Mails von dieser Adresse werden verarbeitet. |
| ziel_ordner | Nein | leer | Folder-ID des zu überwachenden Outlook-Ordners. Leer = alle Ordner. |
| onedrive_basispfad | Nein | Personal | Basispfad in OneDrive für die Ablage. |
| enachrichtigungs_email | Nein | Eigene Mailbox | E-Mail-Adresse für Fehler-Benachrichtigungen. |
| ilter_betreff | Nein | leer | Liste von Begriffen. E-Mail-Betreff muss mindestens einen enthalten. |
| ilter_inhalt | Nein | leer | Liste von Begriffen. E-Mail-Body muss mindestens einen enthalten. |
| lexoffice_api_key | Nein | leer | Lexoffice API-Key. Leer = kein Upload. |
| email_betreff_vorlage | Nein | Ihre Gehaltsabrechnung {monat} | Betreff für E-Mail-Entwürfe. {monat} wird ersetzt. |
| email_text_vorlage | Nein | Anbei Ihre Gehaltsabrechnung für {monat}. | Text für E-Mail-Entwürfe. {monat} wird ersetzt. |

### Mitarbeiter-Stammdaten

| Feld | Pflicht | Beschreibung |
|---|---|---|
| 
ame | Ja | Vollständiger Name (muss exakt mit PDF übereinstimmen) |
| personal_nr | Ja | Personalnummer (muss exakt mit PDF übereinstimmen, z.B. "00001") |
| email | Ja | E-Mail-Adresse für den Outlook-Entwurf |
| onedrive_ordner | Nein | Individueller OneDrive-Pfad. Standard: {basispfad}/{Name_mit_Unterstrichen} |

---

## 12. Fehlerbehandlung und Benachrichtigungen

### Fehler-Szenarien und Reaktionen

| Szenario | Reaktion |
|---|---|
| E-Mail ohne PDF-Anhang | Info-Mail an enachrichtigungs_email |
| PDF nicht lesbar (korrupt) | Fehler-Mail + Log-Eintrag (status: error) |
| PDF > 25 MB | Seite wird übersprungen |
| Mitarbeiter nicht in Stammdaten | PDF in _Unklar/ + Info-Mail nach Verarbeitung |
| OneDrive-Upload fehlgeschlagen | Fehler-Mail pro Mitarbeiter + Log (status: partial) |
| E-Mail-Entwurf fehlgeschlagen | Fehler wird geloggt, Pipeline läuft weiter |
| Lexoffice-Upload fehlgeschlagen | Fehler wird geloggt, Pipeline läuft weiter |
| Microsoft Token abgelaufen | uth_status = "disconnected" in Firestore, Warnung im Frontend |
| Gemini API nicht verfügbar | Fallback auf Text/OCR-Ergebnis, alidierung = "fehler" |

### Kritisch vs. Nicht-kritisch

**Kritische Fehler** (stoppen die Verarbeitung für diesen Mitarbeiter):
- PDF nicht lesbar
- OneDrive-Upload fehlgeschlagen

**Nicht-kritische Fehler** (werden geloggt, Pipeline läuft weiter):
- E-Mail-Entwurf fehlgeschlagen
- Lexoffice-Upload fehlgeschlagen
- Gemini API-Fehler
- Temp-Datei konnte nicht gelöscht werden

### Log-Status

| Status | Bedeutung |
|---|---|
| success | Alle Mitarbeiter verarbeitet, keine Fehler, keine unklaren Seiten |
| partial | Mindestens ein Mitarbeiter verarbeitet, aber auch Fehler oder unklare Seiten |
| error | Kein Mitarbeiter konnte verarbeitet werden |

---

## 13. Deployment

### Backend (Google Cloud Run)

**Service:** ki-lohnabrechner-backend-git
**Region:** europe-west3 (Frankfurt)
**URL:** https://ki-lohnabrechner-backend-git-37257155635.europe-west3.run.app

**Dockerfile:**
`dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-deu
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
`

**Wichtig:** Tesseract OCR mit deutschem Sprachpaket (	esseract-ocr-deu) muss im Container installiert sein.

**Deployment:** Automatisch via Cloud Build bei Push auf GitHub (main-Branch).

**IAM-Berechtigungen für den Service Account (37257155635-compute@developer.gserviceaccount.com):**
- Cloud Datastore-Nutzer (Firestore lesen/schreiben)
- Ersteller von Dienstkonto-Tokens (Firebase Custom Tokens signieren)
- Secret Manager Secret Accessor (falls Secrets über Secret Manager)
- Logs Writer

**Skalierung:** Anfragebasiert (0 Instanzen bei keinem Traffic, skaliert automatisch hoch)

### Frontend (Cloudflare Pages)

**Projekt:** ki-lohnabrechner-frontend
**URL:** https://ki-lohnabrechner-frontend.pages.dev

**Build-Einstellungen:**
- Build command: 
pm run build
- Build output directory: dist
- Node.js Version: 18+

**Deployment:** Automatisch bei Push auf GitHub.

**Wichtig:** Environment Variables müssen in Cloudflare Pages unter "Settings → Environment Variables" gesetzt sein (nicht in der .env Datei, die ist in .gitignore).

### Firebase / Firestore

**Projekt:** lohnabrechner (GCP-Projekt)
**Datenbank:** lohnabrechner (Firestore, europe-west3)
**Authentication:** Aktiviert (für Custom Tokens)

### Azure AD App Registration

**App Name:** KI-Lohnabrechner
**Typ:** Multitenant
**Redirect URIs:**
- Web: https://ki-lohnabrechner-backend-git-37257155635.europe-west3.run.app/api/auth/callback
- Single-Page-Webanwendung: https://ki-lohnabrechner-frontend.pages.dev

**API Permissions (Delegated):**
- User.Read
- Mail.Read
- Mail.ReadWrite
- Files.ReadWrite.All
- offline_access

### Cloud Scheduler (Webhook-Verlängerung)

Täglich aufrufen:
`
GET https://ki-lohnabrechner-backend-git-37257155635.europe-west3.run.app/api/cron/renew
Header: x-api-key: {BACKEND_API_SECRET}
`

---

## 14. Umgebungsvariablen

### Backend (Cloud Run Environment Variables)

| Variable | Beschreibung | Beispiel |
|---|---|---|
| M365_CLIENT_ID | Azure AD Application (Client) ID | 95baf806-39db-... |
| M365_CLIENT_SECRET | Azure AD Client Secret | bc~def... |
| BACKEND_URL | Öffentliche URL des Backends | https://ki-lohnabrechner-backend-git-37257155635.europe-west3.run.app |
| FRONTEND_URL | URL des Frontends (für Redirects) | https://ki-lohnabrechner-frontend.pages.dev |
| BACKEND_API_SECRET | API-Key für Cron-Endpunkt | mein-geheimer-cron-key |
| ENCRYPTION_KEY | Fernet-Key für Datenverschlüsselung | bc123...= (Base64, 32 Bytes) |
| GEMINI_API_KEY | Google AI Studio API-Key | AIzaSy... |
| GEMINI_MODEL | Gemini-Modell | gemini-3.1-pro-preview |

**Encryption Key generieren:**
`ash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
`

### Frontend (Cloudflare Pages Environment Variables)

| Variable | Beschreibung |
|---|---|
| VITE_AZURE_CLIENT_ID | Azure AD Client ID (gleich wie M365_CLIENT_ID) |
| VITE_BACKEND_API_URL | Backend-URL |
| VITE_FIREBASE_API_KEY | Firebase Web API Key |
| VITE_FIREBASE_AUTH_DOMAIN | Firebase Auth Domain |
| VITE_FIREBASE_PROJECT_ID | Firebase Projekt-ID |
| VITE_FIREBASE_STORAGE_BUCKET | Firebase Storage Bucket |
| VITE_FIREBASE_MESSAGING_SENDER_ID | Firebase Messaging Sender ID |
| VITE_FIREBASE_APP_ID | Firebase App ID |

---

*Dokumentation erstellt: April 2026*
*Architektur basiert auf dem ki-buchhalter-Projekt (gleicher Stack, gleiche Auth-Patterns)*
