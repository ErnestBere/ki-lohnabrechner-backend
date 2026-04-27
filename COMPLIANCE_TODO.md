# TODO: Compliance-Härtung (DSGVO & SGB X)

Dieses Dokument beschreibt die notwendigen Schritte zur technischen Absicherung des KI-Lohnabrechners gemäß den Anforderungen für Sozialdaten.

## 1. Secrets & Schlüssel-Management (Prio: Hoch)

Ziel: Weg von Klartext-Umgebungsvariablen hin zum Google Secret Manager.

- [ ] **GCP: Secrets im Secret Manager anlegen**
  - `LOHN_ENCRYPTION_KEY`
  - `LOHN_M365_CLIENT_SECRET`
  - `LOHN_BACKEND_API_SECRET`
  - `LOHN_GEMINI_API_KEY`
- [ ] **Backend: Code auf Secret Manager umstellen**
  - `google-cloud-secret-manager` in `requirements.txt` aufnehmen.
  - Hilfsfunktion `get_secret()` in `main.py` implementieren.
  - Alle `os.environ.get()` Aufrufe für sensible Daten ersetzen.
- [ ] **IAM: Service Account Berechtigungen anpassen**
  - Dem Cloud Run Service Account die Rolle `roles/secretmanager.secretAccessor` für die spezifischen Secrets zuweisen.
- [ ] **Cleanup:** Alle Klartext-Secrets aus den Cloud Run Umgebungsvariablen entfernen.

## 2. Infrastruktur-Isolation (VPC)

Ziel: Datenverkehr zwischen Cloud Run und Firestore/Vertex AI intern halten.

- [ ] **GCP: VPC und Subnetz erstellen** (Region: `europe-west3`).
- [ ] **GCP: Serverless VPC Access Connector einrichten**.
- [ ] **Cloud Run: Egress-Einstellung anpassen**
  - Den Connector mit dem Cloud Run Service verknüpfen.
  - "Route all traffic through the VPC" aktivieren.
- [ ] **GCP: VPC Service Controls (Perimeter) konfigurieren**
  - Perimeter um das Projekt ziehen.
  - Dienste `firestore.googleapis.com` und `aiplatform.googleapis.com` in den Perimeter aufnehmen.

## 3. Verschlüsselung mit CMEK (SGB X Anforderung)

Ziel: Volle Souveränität über die Verschlüsselungsschlüssel.

- [ ] **GCP: Cloud KMS Keyring und Key erstellen**
  - Ort: `europe-west3`.
  - Zweck: Symmetrische Verschlüsselung.
- [ ] **IAM: KMS-Berechtigung für Dienstkonten**
  - Dem Firestore Service Agent die Rolle `roles/cloudkms.cryptoKeyEncrypterDecrypter` für den neuen Key zuweisen.
- [ ] **Firestore: Auf CMEK umstellen**
  - *Hinweis:* Bestehende Datenbanken können oft nicht nachträglich auf CMEK umgestellt werden. Evtl. Export/Import in eine neue, CMEK-geschützte Instanz nötig.

## 4. Audit & Nachweisbarkeit

Ziel: Lückenlose Protokollierung aller Zugriffe auf Sozialdaten.

- [ ] **GCP: Cloud Audit Logs aktivieren**
  - In den IAM-Einstellungen -> Audit Logs.
  - Für Dienst `Cloud Firestore` die Typen `DATA_READ` und `DATA_WRITE` aktivieren.
- [ ] **Logging-Review:** Sicherstellen, dass trotz Audit-Logs keine Klarnamen in den Log-Nachrichten selbst landen (bereits teilweise durch Maskierung umgesetzt).

## 5. Souveränitäts-Check

- [ ] **GCP: "Sovereign Controls by T-Systems" prüfen**
  - Falls verfügbar, Projekt in einen souveränen Folder verschieben, um zusätzliche Compliance-Garantien für den Standort Deutschland zu erhalten.

---
*Status: Geplant*
*Zuständig: IT-Compliance / Plinius Systems*
