"""
KI-Lohnabrechner Backend
========================
Automatisiert die Verarbeitung von Sammel-PDFs mit Gehaltsabrechnungen.
Architektur identisch zum ki-buchhalter: FastAPI + Cloud Run + Firestore + MSAL + Firebase.
"""

import os
import logging

# Strukturiertes Logging für Cloud Run
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(asctime)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ"
)
logger = logging.getLogger(__name__)
import requests
import msal
import secrets
import json
import datetime
import base64
import re
import io

try:
    import fitz  # PyMuPDF
except Exception as e:
    print(f"⚠️ PyMuPDF nicht verfügbar: {e}")
    fitz = None

try:
    import pytesseract
    from PIL import Image
except Exception as e:
    print(f"⚠️ Tesseract/Pillow nicht verfügbar: {e}")
    pytesseract = None

from fastapi import FastAPI, Request, Response, Header, HTTPException, Depends, Security
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import RedirectResponse

try:
    from google import genai
    from google.genai import types
except Exception as e:
    print(f"⚠️ google-genai nicht verfügbar: {e}")
    genai = None
    types = None

try:
    from google.cloud import firestore
except Exception as e:
    print(f"⚠️ Firestore nicht verfügbar: {e}")
    firestore = None

try:
    import firebase_admin
    from firebase_admin import credentials, auth
except Exception as e:
    print(f"⚠️ Firebase Admin nicht verfügbar: {e}")
    firebase_admin = None
    auth = None

try:
    from cryptography.fernet import Fernet
except Exception as e:
    print(f"⚠️ Fernet nicht verfügbar: {e}")
    Fernet = None

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
except Exception as e:
    print(f"⚠️ slowapi nicht verfügbar: {e}")
    Limiter = None

# ==========================================
# 🔧 GLOBALE KONFIGURATION
# ==========================================
CLIENT_ID = os.environ.get("M365_CLIENT_ID")
CLIENT_SECRET = os.environ.get("M365_CLIENT_SECRET")
BACKEND_URL = os.environ.get("BACKEND_URL")
FRONTEND_URL = os.environ.get("FRONTEND_URL")
BACKEND_API_SECRET = os.environ.get("BACKEND_API_SECRET")
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")

# Graph API Scopes (anders als ki-buchhalter: Files statt Calendar/Planner)
GRAPH_SCOPES = ["User.Read", "Mail.Read", "Mail.ReadWrite", "Files.ReadWrite.All"]

if not ENCRYPTION_KEY or not BACKEND_API_SECRET:
    print("⚠️ WARNUNG: ENCRYPTION_KEY oder BACKEND_API_SECRET fehlt! Server startet, aber Auth-Funktionen sind deaktiviert.")
    fernet = None
else:
    fernet = Fernet(ENCRYPTION_KEY)

# Gemini Client (API-Key statt Vertex AI)
gemini_client = None
if GEMINI_API_KEY and genai:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"⚠️ Gemini Client Fehler: {e}")

# Firestore
db = None
if firestore:
    try:
        db = firestore.Client(database="lohnabrechner")
    except Exception as e:
        print(f"⚠️ Firestore nicht verfügbar: {e}")

# Firebase Admin
if firebase_admin:
    try:
        firebase_admin.initialize_app()
    except ValueError:
        pass
    except Exception as e:
        print(f"⚠️ Firebase Admin Init Fehler: {e}")

security = HTTPBearer()

# ==========================================
# 📦 PYDANTIC-MODELLE
# ==========================================

class FirebaseAuthRequest(BaseModel):
    access_token: str
    tenant_id: str

class LohnKundenProfil(BaseModel):
    tenant_id: str
    firmen_name: str
    mailbox_email: str
    steuerbuero_absender: str
    lexoffice_api_key: Optional[str] = None
    ziel_ordner: Optional[str] = ""
    onedrive_basispfad: str = "/Personal"
    email_betreff_vorlage: str = "Ihre Gehaltsabrechnung {monat}"
    email_text_vorlage: str = "Anbei Ihre Gehaltsabrechnung für {monat}."
    filter_betreff: List[str] = []   # E-Mail muss einen dieser Begriffe im Betreff enthalten
    filter_inhalt: List[str] = []    # E-Mail muss einen dieser Begriffe im Body enthalten

class MitarbeiterStamm(BaseModel):
    name: str
    personal_nr: str
    email: str
    onedrive_ordner: Optional[str] = None

class GeminiSeitenInfo(BaseModel):
    ist_lohnabrechnung: bool = Field(description="True wenn die Seite eine individuelle Lohn-/Gehaltsabrechnung ist")
    mitarbeiter_name: Optional[str] = Field(default=None, description="Vollständiger Name des Mitarbeiters")
    personal_nr: Optional[str] = Field(default=None, description="Personalnummer (nur Ziffern)")
    abrechnungsmonat: Optional[str] = Field(default=None, description="Abrechnungsmonat z.B. 'März 2026'")
    seitentyp: str = Field(description="lohnabrechnung, zahlungsuebersicht, sv_nachweis, sonstiges")

class LohnSeitenInfo(BaseModel):
    seite: int
    ist_lohnabrechnung: bool
    mitarbeiter_name: Optional[str] = None
    personal_nr: Optional[str] = None
    abrechnungsmonat: Optional[str] = None
    typ: str = ""
    quelle: str = ""
    gemini_result: Optional[dict] = None
    validierung: str = ""

class SeitenDetail(BaseModel):
    seite: int
    typ: str
    mitarbeiter_name: Optional[str] = None
    personal_nr: Optional[str] = None
    status: str  # zugeordnet, unklar, fehler, uebersprungen
    quelle: str
    validierung: str
    fehler_details: Optional[str] = None

class VerarbeitungsLog(BaseModel):
    timestamp: Optional[Any] = None
    status: str  # success, error, partial
    dateiname: str
    gesamt_seiten: int
    erkannte_mitarbeiter: int
    fehler_anzahl: int
    nicht_zugeordnet: int
    message: str
    seiten_details: List[SeitenDetail]


# ==========================================
# 🚀 FASTAPI APP + MIDDLEWARE
# ==========================================
app = FastAPI()

@app.get("/")
def health_check():
    """Health Check — zeigt ob der Server läuft."""
    return {"status": "ok", "service": "ki-lohnabrechner-backend", "db": db is not None, "gemini": gemini_client is not None}

def get_real_ip(request: Request):
    """Sicheres Auslesen der Client-IP (Cloud Run)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ips = [ip.strip() for ip in xff.split(",") if ip.strip()]
        if ips:
            return ips[-1]
    return request.client.host if request.client else "127.0.0.1"

if Limiter:
    limiter = Limiter(key_func=get_real_ip)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://ki-lohnabrechner-frontend.calm-frost-00c8.workers.dev",
        "https://ki-lohnabrechner-frontend.pages.dev",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 🔐 AUTH + HILFSFUNKTIONEN
# ==========================================

def verify_firebase_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Prüft das Firebase JWT Token für Frontend-Anfragen."""
    token = credentials.credentials
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        print(f"🚨 JWT Fehler: {e}")
        raise HTTPException(status_code=401, detail="Ungültiger oder abgelaufener Token")

def verify_api_key(x_api_key: str = Header(...)):
    """Prüft den API-Key für Server-zu-Server Kommunikation (Cronjobs)."""
    if x_api_key != BACKEND_API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

def encrypt_data(data: str) -> str:
    """Verschlüsselt einen String für die Datenbank (AES/Fernet)."""
    if not data or not fernet:
        return data
    return fernet.encrypt(data.encode()).decode()

def decrypt_data(data: str) -> Optional[str]:
    """Entschlüsselt einen String aus der Datenbank."""
    if not data or not fernet:
        return data
    try:
        return fernet.decrypt(data.encode()).decode()
    except Exception as e:
        print(f"🚨 Verschlüsselungs-Fehler: {e}")
        return None

def get_delegated_token(tenant_id: str, refresh_token: str):
    """Tauscht einen Refresh Token gegen einen Access Token."""
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    msal_app = msal.ConfidentialClientApplication(CLIENT_ID, authority=authority, client_credential=CLIENT_SECRET)
    return msal_app.acquire_token_by_refresh_token(refresh_token, scopes=GRAPH_SCOPES)

def handle_token_error(token_result: dict, tenant_id: str, mailbox_email: str):
    """Prüft ob der MS Refresh Token abgelaufen ist und updatet die DB."""
    if "error" in token_result:
        error_code = token_result.get("error")
        if error_code in ["invalid_grant", "interaction_required"]:
            print(f"🚨 AUTH-FEHLER: Token für {mailbox_email} (Tenant: {tenant_id}) abgelaufen!")
            try:
                db.collection("lohn_kunden").document(tenant_id).collection("postfaecher").document(mailbox_email).update({
                    "auth_status": "disconnected",
                    "auth_error": "Microsoft-Verbindung getrennt. Bitte neu autorisieren.",
                    "disconnected_at": firestore.SERVER_TIMESTAMP
                })
            except Exception as e:
                print(f"Fehler beim Update des Auth-Status: {e}")
        return True
    return False

def setup_m365_webhook(tenant_id: str, mailbox_email: str, access_token: str, ziel_ordner: str):
    """Löscht den alten Webhook und legt einen neuen an."""
    pf_ref = db.collection("lohn_kunden").document(tenant_id).collection("postfaecher").document(mailbox_email)
    pf_doc = pf_ref.get()

    alte_sub_id = None
    if pf_doc.exists:
        alte_sub_id = pf_doc.to_dict().get("subscription_id")

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    if alte_sub_id:
        try:
            requests.delete(f"https://graph.microsoft.com/v1.0/subscriptions/{alte_sub_id}", headers=headers)
        except Exception:
            pass

    sicherer_client_state = secrets.token_hex(32)
    WEBHOOK_URL = f"{BACKEND_URL}/webhook/m365"
    new_expire = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # Resource-Pfad: Mit oder ohne Ordner-Filter
    if ziel_ordner:
        resource = f"users/{mailbox_email}/mailFolders('{ziel_ordner}')/messages?$filter=hasAttachments eq true"
    else:
        resource = f"users/{mailbox_email}/messages?$filter=hasAttachments eq true"

    post_payload = {
        "changeType": "created",
        "notificationUrl": WEBHOOK_URL,
        "resource": resource,
        "expirationDateTime": new_expire,
        "clientState": sicherer_client_state
    }

    sub_res = requests.post("https://graph.microsoft.com/v1.0/subscriptions", headers=headers, json=post_payload)

    if sub_res.status_code == 201:
        pf_ref.update({
            "subscription_id": sub_res.json().get("id"),
            "client_state": sicherer_client_state,
            "auth_status": "connected",
            "auth_error": None
        })
        return True
    else:
        print(f"🚨 MICROSOFT WEBHOOK FEHLER: {sub_res.text}")
        return False


# ==========================================
# 🔑 AUTH-ENDPUNKTE
# ==========================================

@app.post("/api/auth/firebase")
async def create_firebase_token(req: FirebaseAuthRequest):
    """Firebase Custom Token aus Microsoft Access Token erstellen."""
    headers = {"Authorization": f"Bearer {req.access_token}"}
    res = requests.get("https://graph.microsoft.com/v1.0/me", headers=headers)

    if res.status_code != 200:
        print(f"🚨 MS Token ungültig: {res.text}")
        raise HTTPException(status_code=401, detail="Ungültiger Microsoft Token")

    ms_user = res.json()
    ms_user_id = ms_user.get("id")

    try:
        custom_token = auth.create_custom_token(
            uid=ms_user_id,
            developer_claims={"tid": req.tenant_id}
        )
        return {"firebase_token": custom_token.decode("utf-8")}
    except Exception as e:
        print(f"🚨 Firebase Token Fehler: {e}")
        raise HTTPException(status_code=500, detail="Interner Auth-Fehler")


@app.get("/api/auth/callback")
def microsoft_callback(code: str, state: str):
    """OAuth2 Callback — User kommt von Microsoft zurück."""
    try:
        state_data = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
        tenant_id = state_data.get("t")
        mailbox_email = state_data.get("m")

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        msal_app = msal.ConfidentialClientApplication(CLIENT_ID, authority=authority, client_credential=CLIENT_SECRET)

        redirect_uri = f"{BACKEND_URL}/api/auth/callback"
        token_result = msal_app.acquire_token_by_authorization_code(
            code=code, scopes=GRAPH_SCOPES, redirect_uri=redirect_uri
        )

        if "error" in token_result:
            print(f"🚨 Auth-Fehler: {token_result.get('error_description')}")
            return RedirectResponse(url=f"{FRONTEND_URL}/dashboard?error=auth_failed")

        access_token = token_result["access_token"]
        refresh_token = token_result.get("refresh_token")

        pf_ref = db.collection("lohn_kunden").document(tenant_id).collection("postfaecher").document(mailbox_email)
        pf_ref.update({"m365_refresh_token": encrypt_data(refresh_token)})

        ziel_ordner = pf_ref.get().to_dict().get("ziel_ordner", "")
        setup_m365_webhook(tenant_id, mailbox_email, access_token, ziel_ordner)

        return RedirectResponse(url=f"{FRONTEND_URL}/dashboard?success=true")
    except Exception as e:
        return f"Fehler bei der Microsoft-Verbindung: {e}"


# ==========================================
# 📝 REGISTRIERUNG + KONFIGURATION
# ==========================================

@app.post("/api/register")
def register_customer(profil: LohnKundenProfil, user_token: dict = Depends(verify_firebase_token)):
    """Kundenkonfiguration speichern + Webhook einrichten."""
    user_id = user_token.get("uid")
    tenant_claim = user_token.get("tid")

    if profil.tenant_id not in [user_id, tenant_claim]:
        raise HTTPException(status_code=403, detail="Keine Berechtigung für diesen Tenant.")

    try:
        tenant_ref = db.collection("lohn_kunden").document(profil.tenant_id)
        update_data = {
            "firmen_name": profil.firmen_name,
            "steuerbuero_absender": profil.steuerbuero_absender,
            "email_betreff_vorlage": profil.email_betreff_vorlage,
            "email_text_vorlage": profil.email_text_vorlage,
            "onedrive_basispfad": profil.onedrive_basispfad,
            "filter_betreff": profil.filter_betreff,
            "filter_inhalt": profil.filter_inhalt,
        }

        if profil.lexoffice_api_key and profil.lexoffice_api_key != "********":
            update_data["lexoffice_api_key"] = encrypt_data(profil.lexoffice_api_key)

        tenant_ref.set(update_data, merge=True)

        pf_ref = tenant_ref.collection("postfaecher").document(profil.mailbox_email)
        pf_doc = pf_ref.get()
        refresh_token = decrypt_data(pf_doc.to_dict().get("m365_refresh_token")) if pf_doc.exists else None

        postfach_daten = profil.model_dump(exclude={"lexoffice_api_key", "firmen_name", "steuerbuero_absender", "email_betreff_vorlage", "email_text_vorlage"})
        pf_ref.set(postfach_daten, merge=True)

        authority = f"https://login.microsoftonline.com/{profil.tenant_id}"
        msal_app = msal.ConfidentialClientApplication(CLIENT_ID, authority=authority, client_credential=CLIENT_SECRET)

        if refresh_token:
            token_result = msal_app.acquire_token_by_refresh_token(refresh_token, scopes=GRAPH_SCOPES)
            if not handle_token_error(token_result, profil.tenant_id, profil.mailbox_email):
                erfolg = setup_m365_webhook(profil.tenant_id, profil.mailbox_email, token_result["access_token"], profil.ziel_ordner)
                if erfolg:
                    return {"status": "success", "message": "Konfiguration erfolgreich gespeichert!"}
                else:
                    raise HTTPException(status_code=500, detail="Microsoft hat den Webhook abgelehnt.")

        # Kein Token → Microsoft Login URL generieren
        state_data = json.dumps({"t": profil.tenant_id, "m": profil.mailbox_email})
        state_encoded = base64.urlsafe_b64encode(state_data.encode()).decode()
        redirect_uri = f"{BACKEND_URL}/api/auth/callback"
        auth_url = msal_app.get_authorization_request_url(GRAPH_SCOPES, state=state_encoded, redirect_uri=redirect_uri)

        return {"status": "auth_required", "auth_url": auth_url}

    except Exception as e:
        print(f"❌ INTERNER FEHLER in /register: {e}")
        return Response(content="Ein interner Serverfehler ist aufgetreten.", status_code=500)


# ==========================================
# 🔄 CRON: WEBHOOK-VERLÄNGERUNG
# ==========================================

@app.get("/api/cron/renew")
def renew_webhooks(api_key_check: None = Depends(verify_api_key)):
    """Verlängert alle aktiven Webhooks (Cloud Scheduler, alle 24h)."""
    renewed = 0
    errors = 0

    for tenant_doc in db.collection("lohn_kunden").stream():
        tenant_id = tenant_doc.id
        for pf_doc in db.collection("lohn_kunden").document(tenant_id).collection("postfaecher").stream():
            postfach = pf_doc.to_dict()
            sub_id = postfach.get("subscription_id")
            refresh_token = decrypt_data(postfach.get("m365_refresh_token"))

            if not sub_id or not refresh_token:
                continue

            try:
                token_result = get_delegated_token(tenant_id, refresh_token)
                if handle_token_error(token_result, tenant_id, pf_doc.id):
                    errors += 1
                    continue

                headers = {"Authorization": f"Bearer {token_result['access_token']}", "Content-Type": "application/json"}
                new_expire = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")

                res = requests.patch(
                    f"https://graph.microsoft.com/v1.0/subscriptions/{sub_id}",
                    headers=headers,
                    json={"expirationDateTime": new_expire}
                )

                if res.status_code == 200:
                    renewed += 1
                else:
                    print(f"⚠️ Webhook-Verlängerung fehlgeschlagen für {pf_doc.id}: {res.text}")
                    errors += 1
            except Exception as e:
                print(f"❌ Fehler bei Webhook-Verlängerung: {e}")
                errors += 1

    return {"renewed": renewed, "errors": errors}


# ==========================================
# 👥 MITARBEITER CRUD
# ==========================================

@app.get("/api/mitarbeiter")
def get_mitarbeiter(user_token: dict = Depends(verify_firebase_token)):
    """Alle Mitarbeiter eines Kunden laden."""
    tenant_id = user_token.get("tid") or user_token.get("uid")
    mitarbeiter = []
    for doc in db.collection("lohn_kunden").document(tenant_id).collection("mitarbeiter").stream():
        ma = doc.to_dict()
        ma["id"] = doc.id
        mitarbeiter.append(ma)
    return {"mitarbeiter": mitarbeiter}


@app.post("/api/mitarbeiter")
def create_mitarbeiter(ma: MitarbeiterStamm, user_token: dict = Depends(verify_firebase_token)):
    """Mitarbeiter anlegen mit Eindeutigkeitsprüfung der Personalnummer."""
    tenant_id = user_token.get("tid") or user_token.get("uid")
    ma_ref = db.collection("lohn_kunden").document(tenant_id).collection("mitarbeiter")

    # Eindeutigkeitsprüfung
    existing = ma_ref.where("personal_nr", "==", ma.personal_nr).limit(1).stream()
    if any(True for _ in existing):
        raise HTTPException(status_code=409, detail=f"Personalnummer {ma.personal_nr} existiert bereits.")

    # OneDrive-Ordner aus Name generieren falls leer
    ordner = ma.onedrive_ordner or f"/Personal/{ma.name.replace(' ', '_')}"
    data = ma.model_dump()
    data["onedrive_ordner"] = ordner
    data["erstellt_am"] = firestore.SERVER_TIMESTAMP

    doc_ref = ma_ref.add(data)
    return {"id": doc_ref[1].id, "message": "Mitarbeiter angelegt."}


@app.put("/api/mitarbeiter/{ma_id}")
def update_mitarbeiter(ma_id: str, ma: MitarbeiterStamm, user_token: dict = Depends(verify_firebase_token)):
    """Mitarbeiter bearbeiten."""
    tenant_id = user_token.get("tid") or user_token.get("uid")
    doc_ref = db.collection("lohn_kunden").document(tenant_id).collection("mitarbeiter").document(ma_id)

    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Mitarbeiter nicht gefunden.")

    # PNr-Eindeutigkeit prüfen (außer bei sich selbst)
    ma_ref = db.collection("lohn_kunden").document(tenant_id).collection("mitarbeiter")
    for doc in ma_ref.where("personal_nr", "==", ma.personal_nr).stream():
        if doc.id != ma_id:
            raise HTTPException(status_code=409, detail=f"Personalnummer {ma.personal_nr} existiert bereits.")

    ordner = ma.onedrive_ordner or f"/Personal/{ma.name.replace(' ', '_')}"
    data = ma.model_dump()
    data["onedrive_ordner"] = ordner
    doc_ref.update(data)
    return {"message": "Mitarbeiter aktualisiert."}


@app.delete("/api/mitarbeiter/{ma_id}")
def delete_mitarbeiter(ma_id: str, user_token: dict = Depends(verify_firebase_token)):
    """Mitarbeiter löschen."""
    tenant_id = user_token.get("tid") or user_token.get("uid")
    doc_ref = db.collection("lohn_kunden").document(tenant_id).collection("mitarbeiter").document(ma_id)

    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Mitarbeiter nicht gefunden.")

    doc_ref.delete()
    return {"message": "Mitarbeiter gelöscht."}


# ==========================================
# 🗑️ WEBHOOK LÖSCHEN
# ==========================================

@app.delete("/api/webhook/{tenant_id}/{mailbox_email}")
def delete_webhook(tenant_id: str, mailbox_email: str, user_token: dict = Depends(verify_firebase_token)):
    """Webhook + Postfach löschen."""
    uid = user_token.get("uid")
    tid = user_token.get("tid")
    if tenant_id not in [uid, tid]:
        raise HTTPException(status_code=403, detail="Keine Berechtigung.")

    pf_ref = db.collection("lohn_kunden").document(tenant_id).collection("postfaecher").document(mailbox_email)
    pf_doc = pf_ref.get()

    if pf_doc.exists:
        sub_id = pf_doc.to_dict().get("subscription_id")
        refresh_token = decrypt_data(pf_doc.to_dict().get("m365_refresh_token"))

        if sub_id and refresh_token:
            try:
                token_result = get_delegated_token(tenant_id, refresh_token)
                if "access_token" in token_result:
                    headers = {"Authorization": f"Bearer {token_result['access_token']}"}
                    requests.delete(f"https://graph.microsoft.com/v1.0/subscriptions/{sub_id}", headers=headers)
            except Exception:
                pass

        pf_ref.delete()

    return {"message": "Webhook und Postfach gelöscht."}


# ==========================================
# 📨 WEBHOOK: E-MAIL EMPFANG
# ==========================================

@app.post("/webhook/m365")
async def m365_webhook(request: Request):
    """Microsoft Graph Webhook-Empfänger für eingehende E-Mails."""
    # Validation Token für Webhook-Registrierung
    if "validationToken" in request.query_params:
        return Response(content=request.query_params["validationToken"], media_type="text/plain", status_code=200)

    logger.info("🔔 LOHN-WEBHOOK EMPFANGEN!")
    body = await request.json()

    for value in body.get("value", []):
        resource_data = value.get("resourceData", {})
        message_id = resource_data.get("id")
        customer_tenant_id = value.get("tenantId")
        resource_path = value.get("resource", "")

        if not message_id or not customer_tenant_id:
            continue

        # Duplikat-Schutz
        mail_doc_ref = db.collection("lohn_processed_mails").document(message_id)
        if mail_doc_ref.get().exists:
            print("⏭️ Mail bereits verarbeitet.")
            continue

        mail_doc_ref.set({"status": "processing", "received_at": firestore.SERVER_TIMESTAMP})

        subscription_id = value.get("subscriptionId")
        incoming_client_state = value.get("clientState")

        # Postfach über Webhook-ID finden
        postfaecher_ref = db.collection("lohn_kunden").document(customer_tenant_id).collection("postfaecher").where("subscription_id", "==", subscription_id).stream()
        postfach = None
        for doc in postfaecher_ref:
            postfach = doc.to_dict()
            break

        if not postfach:
            print("⚠️ Kein passendes Postfach gefunden.")
            continue

        # clientState-Validierung
        erwarteter_state = postfach.get("client_state")
        if erwarteter_state and incoming_client_state != erwarteter_state:
            print(f"🚨 SICHERHEITSWARNUNG: Falscher clientState! Webhook ignoriert.")
            continue

        # Tenant-Daten laden
        tenant_doc = db.collection("lohn_kunden").document(customer_tenant_id).get()
        kunde = tenant_doc.to_dict() if tenant_doc.exists else {}

        MAILBOX_EMAIL = postfach.get("mailbox_email")
        REFRESH_TOKEN = decrypt_data(postfach.get("m365_refresh_token"))
        LEXOFFICE_API_KEY = decrypt_data(kunde.get("lexoffice_api_key"))
        STEUERBUERO_ABSENDER = kunde.get("steuerbuero_absender", "").lower()
        EMAIL_BETREFF = kunde.get("email_betreff_vorlage", "Ihre Gehaltsabrechnung {monat}")
        EMAIL_TEXT = kunde.get("email_text_vorlage", "Anbei Ihre Gehaltsabrechnung für {monat}.")

        # M365 Token holen
        token_result = get_delegated_token(customer_tenant_id, REFRESH_TOKEN)
        if handle_token_error(token_result, customer_tenant_id, MAILBOX_EMAIL):
            continue

        if "access_token" not in token_result:
            continue

        headers = {"Authorization": f"Bearer {token_result['access_token']}", "Content-Type": "application/json"}

        # Absender-Filter + Betreff/Inhalt-Filter prüfen
        mail_res = requests.get(f"https://graph.microsoft.com/v1.0/{resource_path}?$select=subject,from,body", headers=headers)
        if mail_res.status_code == 200:
            mail_data = mail_res.json()
            mail_sender = mail_data.get("from", {}).get("emailAddress", {}).get("address", "").lower()
            mail_subject = (mail_data.get("subject") or "").lower()
            mail_body = (mail_data.get("body", {}).get("content") or "").lower()

            # Absender-Filter
            if STEUERBUERO_ABSENDER and mail_sender != STEUERBUERO_ABSENDER:
                logger.info(f"⏭️ Absender-Filter: {mail_sender} != {STEUERBUERO_ABSENDER}")
                continue

            # Betreff-Filter (optional): mindestens einer muss matchen
            filter_betreff = kunde.get("filter_betreff", [])
            if filter_betreff:
                if not any(f.lower() in mail_subject for f in filter_betreff):
                    logger.info(f"⏭️ Betreff-Filter: kein Match | betreff={mail_subject[:80]}")
                    continue

            # Inhalt-Filter (optional): mindestens einer muss matchen
            filter_inhalt = kunde.get("filter_inhalt", [])
            if filter_inhalt:
                if not any(f.lower() in mail_body for f in filter_inhalt):
                    logger.info(f"⏭️ Inhalt-Filter: kein Match")
                    continue

        # PDF-Anhänge laden
        meta_url = f"https://graph.microsoft.com/v1.0/{resource_path}/attachments?$select=id,name,size"
        att_meta_res = requests.get(meta_url, headers=headers)

        pdf_found = False
        for att_meta in att_meta_res.json().get("value", []):
            filename = att_meta.get("name", "")
            att_size = att_meta.get("size", 0)
            att_id = att_meta.get("id")

            if not filename.lower().endswith(".pdf"):
                continue

            pdf_found = True
            MAX_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB

            if att_size > MAX_SIZE_BYTES:
                print(f"🛡️ PDF zu groß: {filename} ({att_size / 1024 / 1024:.1f} MB)")
                # TODO: Info-Mail an Thomas (Task 7.2)
                continue

            print(f"⬇️ Lade '{filename}' ({att_size / 1024 / 1024:.2f} MB)...")
            content_url = f"https://graph.microsoft.com/v1.0/{resource_path}/attachments/{att_id}"
            content_res = requests.get(content_url, headers=headers)
            pdf_base64 = content_res.json().get("contentBytes")

        if pdf_base64:
                pdf_bytes = base64.b64decode(pdf_base64)
                # Verarbeitungspipeline starten
                await process_sammel_pdf(
                    pdf_bytes=pdf_bytes,
                    filename=filename,
                    tenant_id=customer_tenant_id,
                    mailbox_email=MAILBOX_EMAIL,
                    access_token=token_result["access_token"],
                    lexoffice_api_key=LEXOFFICE_API_KEY,
                    steuerbuero_absender=STEUERBUERO_ABSENDER,
                    email_betreff=EMAIL_BETREFF,
                    email_text=EMAIL_TEXT,
                    onedrive_basispfad=kunde.get("onedrive_basispfad", "/Personal"),
                )

        if not pdf_found:
            print("⚠️ Keine PDF-Anhänge gefunden.")
            send_notification_email(
                token_result["access_token"], MAILBOX_EMAIL,
                "KI-Lohnabrechner: Kein PDF-Anhang",
                "Eine E-Mail vom Steuerbüro wurde empfangen, enthielt aber keinen PDF-Anhang."
            )

        # Status aktualisieren
        mail_doc_ref.update({"status": "done", "processed_at": firestore.SERVER_TIMESTAMP})

    return Response(status_code=202)


# ==========================================
# 📄 PARSER: 3-STUFEN-PIPELINE
# ==========================================

MONAT_MAP = {
    "Januar": "01", "Februar": "02", "März": "03", "April": "04",
    "Mai": "05", "Juni": "06", "Juli": "07", "August": "08",
    "September": "09", "Oktober": "10", "November": "11", "Dezember": "12"
}


def extract_from_text(text: str) -> dict:
    """Stufe 1: Regex-basierte Extraktion aus PDF-Text-Layer."""
    result = {"name": None, "pnr": None, "monat": None, "typ": None}
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    if "Übersicht Zahlungen" in text or "Zahlungen im" in text:
        result["typ"] = "zahlungsuebersicht"
        m = re.search(r"(?:Zahlungen im|für)\s+(\w+\s+\d{4})", text)
        if m:
            result["monat"] = m.group(1)
        return result

    lohn_kw = ["Abrechnung der Brutto", "Brutto/Netto", "Pers.-Nr.",
               "Personal-Nr.", "NETTO-VERDIENST", "Gesamt-Brutto", "Brutto-Bezüge"]
    if any(kw in text for kw in lohn_kw):
        result["typ"] = "lohnabrechnung"

        for pat in [r"\*?Pers\.?\s*-?\s*Nr\.?\s*(\d{3,})\*?", r"Personal\s*-?\s*Nr\.?\s*(\d{3,})"]:
            m = re.search(pat, text)
            if m:
                result["pnr"] = m.group(1)
                break

        m = re.search(r"für\s+(\w+\s+\d{4})", text)
        if m:
            result["monat"] = m.group(1)

        found_pnr = found_firma = False
        for line in lines:
            if "Pers.-Nr." in line or "Personal-Nr." in line:
                found_pnr = True
                continue
            if "projektwärts" in line.lower() or ("*" in line and "Str." in line):
                found_firma = True
                continue
            if found_pnr and found_firma:
                skip = ["Brutto", "Lohnart", "Gehalt", "Netto", "Steuer", "Hinweis",
                        "Eintritt", "Austritt", "Gesamt", "AUSZAHLUNG", "Bezeichnung",
                        "Einheit", "B/M", "B/N", "601", "602", "Anw.", "Urlaub"]
                if (len(line) > 3 and not line[0].isdigit() and "*" not in line
                    and not any(sw in line for sw in skip)
                    and len(line.split()) >= 2
                    and re.match(r"^[A-ZÄÖÜa-zäöüß\s\-\.]+$", line)):
                    result["name"] = line.strip()
                    break
    return result


def extract_from_ocr(page) -> tuple[dict, str]:
    """Stufe 2: Tesseract OCR mit 300 DPI."""
    pix = page.get_pixmap(dpi=300)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    ocr_text = pytesseract.image_to_string(img, lang="deu")

    result = {"name": None, "pnr": None, "monat": None, "typ": None}
    lines = [l.strip() for l in ocr_text.split("\n") if l.strip()]

    lohn_kw = ["Abrechnung der Brutto", "Brutto/Netto", "Pers.-Nr.", "Pers.—Nr.",
               "NETTO-VERDIENST", "Gesamt-Brutto", "Brutto-Bezüge", "Personal-Nr."]
    if any(kw in ocr_text for kw in lohn_kw):
        result["typ"] = "lohnabrechnung"

        for pat in [r"\*?Pers\.?\s*[\-—]?\s*Nr\.?\s*(\d{3,})\*?",
                    r"Personal\s*-?\s*Nr\.?\s*(\d{3,})",
                    r"[Pp]ers\s*[\._\-]\s*[NnXx]r\.?\s*(\d{3,})"]:
            m = re.search(pat, ocr_text)
            if m:
                result["pnr"] = m.group(1)
                break

        m = re.search(r"für\s+(\w+\s+\d{4})", ocr_text)
        if m:
            result["monat"] = m.group(1)

        for line in lines:
            pnr_in_line = re.search(r"(.+?)\s*\*?\s*[Pp]ers\.?\s*[\._\-—]?\s*[NnXx]r\.?\s*\d+", line)
            if pnr_in_line:
                candidate = pnr_in_line.group(1).strip().rstrip("*").strip()
                candidate = re.sub(r"[zZ]pers$", "", candidate).strip()
                candidate = re.sub(r"[zZ]$", "", candidate).strip()
                if len(candidate) > 2 and len(candidate.split()) >= 2:
                    result["name"] = candidate
                    break

    elif "Übersicht Zahlungen" in ocr_text or "Zahlungen im" in ocr_text:
        result["typ"] = "zahlungsuebersicht"
        m = re.search(r"(?:Zahlungen im|für)\s+(\w+\s+\d{4})", ocr_text)
        if m:
            result["monat"] = m.group(1)

    return result, ocr_text


def validate_with_gemini(page_bytes: bytes, page_num: int) -> GeminiSeitenInfo | None:
    """Stufe 3: Gemini Vision Validierung."""
    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Content(parts=[
                    types.Part.from_bytes(data=page_bytes, mime_type="application/pdf"),
                    types.Part.from_text(text=f"Analysiere Seite {page_num} dieser Lohnabrechnung. Extrahiere Mitarbeitername, Personalnummer und Abrechnungsmonat."),
                ])
            ],
            config=types.GenerateContentConfig(
                system_instruction="Du bist ein Experte für deutsche DATEV-Lohnabrechnungen. Extrahiere präzise: Mitarbeitername, Personalnummer, Abrechnungsmonat. Bei geschwärzten Feldern: Null. Antworte NUR mit JSON.",
                response_mime_type="application/json",
                response_schema=GeminiSeitenInfo,
                temperature=0.1,
            ),
        )
        return GeminiSeitenInfo.model_validate_json(response.text)
    except Exception as e:
        print(f"⚠️ Gemini-Fehler Seite {page_num}: {e}")
        return None


def process_page(page, page_num: int) -> LohnSeitenInfo:
    """Verarbeitet eine Seite mit der 3-Stufen-Pipeline."""
    info = LohnSeitenInfo(seite=page_num, ist_lohnabrechnung=False)

    raw_text = page.get_text().strip()
    text_result = extract_from_text(raw_text)
    has_good_text = text_result["typ"] is not None and len(raw_text) > 100

    ocr_result = {"name": None, "pnr": None, "monat": None, "typ": None}
    images = page.get_images(full=True)
    needs_ocr = not has_good_text and (images or len(raw_text) < 50)
    if needs_ocr:
        ocr_result, _ = extract_from_ocr(page)

    local_name = text_result["name"] or ocr_result["name"]
    local_pnr = text_result["pnr"] or ocr_result["pnr"]
    local_monat = text_result["monat"] or ocr_result["monat"]
    local_typ = text_result["typ"] or ocr_result["typ"] or "unbekannt"
    local_quelle = "text" if has_good_text else ("ocr" if needs_ocr else "text")

    # Gemini Vision (immer)
    single_doc = fitz.open()
    single_doc.insert_pdf(page.parent, from_page=page_num - 1, to_page=page_num - 1)
    page_bytes = single_doc.tobytes()
    single_doc.close()

    gemini_info = validate_with_gemini(page_bytes, page_num)

    if gemini_info:
        info.gemini_result = gemini_info.model_dump()
        g_name = gemini_info.mitarbeiter_name
        g_pnr = gemini_info.personal_nr

        if local_name and g_name:
            if local_name.lower().strip() == g_name.lower().strip():
                info.validierung = "match"
                info.mitarbeiter_name = local_name
            else:
                info.validierung = "korrigiert"
                info.mitarbeiter_name = g_name
        elif g_name and not local_name:
            info.validierung = "nur_gemini"
            info.mitarbeiter_name = g_name
        elif local_name and not g_name:
            info.validierung = "nur_lokal"
            info.mitarbeiter_name = local_name
        else:
            info.validierung = "nicht_erkannt"

        info.personal_nr = local_pnr or g_pnr
        if local_pnr and g_pnr and local_pnr != g_pnr:
            info.personal_nr = g_pnr

        info.abrechnungsmonat = local_monat or gemini_info.abrechnungsmonat
        info.ist_lohnabrechnung = gemini_info.ist_lohnabrechnung
        info.typ = gemini_info.seitentyp if gemini_info.ist_lohnabrechnung else local_typ
        info.quelle = f"{local_quelle}+gemini"
    else:
        info.mitarbeiter_name = local_name
        info.personal_nr = local_pnr
        info.abrechnungsmonat = local_monat
        info.ist_lohnabrechnung = local_typ == "lohnabrechnung"
        info.typ = local_typ
        info.quelle = local_quelle
        info.validierung = "fehler"

    return info


def generate_filename(name: str, monat: str) -> str:
    """Erzeugt Dateiname: Gehaltsabrechnung_<Name>_<MM-YYYY>.pdf"""
    name_clean = name.replace(" ", "_")
    parts = monat.split() if monat else []
    if len(parts) == 2 and parts[0] in MONAT_MAP:
        monat_fmt = f"{MONAT_MAP[parts[0]]}-{parts[1]}"
    else:
        monat_fmt = monat.replace(" ", "-") if monat else "unbekannt"
    return f"Gehaltsabrechnung_{name_clean}_{monat_fmt}.pdf"


def create_single_pdf(doc, pages: list[int]) -> bytes:
    """Erzeugt eine Einzel-PDF aus einer Liste von Seitennummern (1-basiert)."""
    new_doc = fitz.open()
    for page_num in pages:
        new_doc.insert_pdf(doc, from_page=page_num - 1, to_page=page_num - 1)
    pdf_bytes = new_doc.tobytes()
    new_doc.close()
    return pdf_bytes


# ==========================================
# 👥 MITARBEITER-ZUORDNUNG
# ==========================================

def match_mitarbeiter(personal_nr: str | None, name: str | None, stammdaten: list[dict]) -> dict | None:
    """Ordnet eine Abrechnung einem Mitarbeiter zu. PNr zuerst, dann Name."""
    if personal_nr:
        for ma in stammdaten:
            if ma.get("personal_nr") == personal_nr:
                return ma

    if name:
        name_lower = name.lower().strip()
        for ma in stammdaten:
            if ma.get("name", "").lower().strip() == name_lower:
                return ma

    return None


# ==========================================
# 📁 GRAPH-CLIENT: ONEDRIVE + E-MAIL
# ==========================================

def upload_to_onedrive(access_token: str, user_email: str, folder_path: str, filename: str, content: bytes) -> dict | None:
    """Lädt eine Datei in OneDrive hoch. Erstellt Ordner falls nötig."""
    headers = {"Authorization": f"Bearer {access_token}"}

    # Ordner erstellen (rekursiv über den Pfad)
    path_parts = [p for p in folder_path.strip("/").split("/") if p]
    current_path = ""
    for part in path_parts:
        current_path = f"{current_path}/{part}" if current_path else part
        create_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{current_path}"
        check = requests.get(create_url, headers=headers)
        if check.status_code == 404:
            parent = "/".join(current_path.split("/")[:-1])
            parent_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{parent}:/children" if parent else f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root/children"
            requests.post(parent_url, headers={**headers, "Content-Type": "application/json"},
                         json={"name": part, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})

    # Datei hochladen
    upload_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{folder_path}/{filename}:/content"
    res = requests.put(upload_url, headers={**headers, "Content-Type": "application/pdf"}, data=content)

    if res.status_code in [200, 201]:
        print(f"  📁 OneDrive: {folder_path}/{filename} hochgeladen.")
        return res.json()
    else:
        print(f"  ❌ OneDrive Upload fehlgeschlagen: {res.status_code} {res.text[:200]}")
        return None


def delete_onedrive_file(access_token: str, user_email: str, file_path: str):
    """Löscht eine Datei aus OneDrive."""
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{file_path}"
    requests.delete(url, headers=headers)


def create_draft_email(access_token: str, user_email: str, to_email: str, subject: str, body: str, attachment_bytes: bytes, attachment_name: str) -> dict | None:
    """Erstellt einen E-Mail-Entwurf mit PDF-Anhang in Outlook."""
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    payload = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": body},
        "toRecipients": [{"emailAddress": {"address": to_email}}],
        "attachments": [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": attachment_name,
            "contentType": "application/pdf",
            "contentBytes": base64.b64encode(attachment_bytes).decode()
        }]
    }

    res = requests.post(f"https://graph.microsoft.com/v1.0/users/{user_email}/messages", headers=headers, json=payload)

    if res.status_code == 201:
        print(f"  ✉️ Entwurf erstellt für {to_email}")
        return res.json()
    else:
        print(f"  ❌ Entwurf fehlgeschlagen: {res.status_code} {res.text[:200]}")
        return None


def send_notification_email(access_token: str, user_email: str, subject: str, body: str):
    """Sendet eine Info-/Fehler-Mail an den Benutzer selbst."""
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {
        "message": {
            "subject": f"[KI-Lohnabrechner] {subject}",
            "body": {"contentType": "HTML", "content": body},
            "toRecipients": [{"emailAddress": {"address": user_email}}]
        },
        "saveToSentItems": True
    }
    requests.post(f"https://graph.microsoft.com/v1.0/users/{user_email}/sendMail", headers=headers, json=payload)


# ==========================================
# 📤 LEXOFFICE-CLIENT
# ==========================================

def upload_to_lexoffice(api_key: str, pdf_bytes: bytes, filename: str) -> dict | None:
    """Lädt ein Dokument als 'Sonstiges' in Lexoffice hoch."""
    if not api_key:
        print("  ⏭️ Kein Lexoffice API-Key — Upload übersprungen.")
        return None

    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    files = {"file": (filename, pdf_bytes, "application/pdf")}
    data = {"type": "voucher"}

    for attempt in range(3):
        res = requests.post("https://api.lexoffice.io/v1/files", headers=headers, files=files, data=data)
        if res.status_code == 202:
            print(f"  📤 Lexoffice: {filename} hochgeladen.")
            return res.json()
        elif res.status_code == 429:
            print(f"  ⏳ Lexoffice Rate Limit — Warte 3s (Versuch {attempt + 1}/3)")
            import time
            time.sleep(3)
        else:
            print(f"  ❌ Lexoffice Fehler: {res.status_code} {res.text[:200]}")
            return None
    return None


# ==========================================
# 🔄 VERARBEITUNGSPIPELINE
# ==========================================

async def process_sammel_pdf(
    pdf_bytes: bytes,
    filename: str,
    tenant_id: str,
    mailbox_email: str,
    access_token: str,
    lexoffice_api_key: str | None,
    steuerbuero_absender: str,
    email_betreff: str,
    email_text: str,
    onedrive_basispfad: str = "/Personal",
):
    """Hauptpipeline: Sammel-PDF zerlegen, zuordnen, ablegen, Entwürfe erstellen."""
    logger.info(f"🔄 PIPELINE START | tenant={tenant_id} | datei={filename}")

    seiten_details = []
    erkannte = 0
    fehler = 0
    unklar = 0

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"❌ PDF nicht lesbar | datei={filename} | fehler={e}")
        try:
            send_notification_email(access_token, mailbox_email, "PDF nicht lesbar", f"Die Datei '{filename}' konnte nicht geöffnet werden: {e}")
        except Exception as mail_err:
            logger.error(f"❌ Info-Mail fehlgeschlagen: {mail_err}")
        write_verarbeitungs_log(tenant_id, filename, 0, 0, 1, 0, "error", f"PDF nicht lesbar: {e}", [])
        return

    gesamt_seiten = doc.page_count
    logger.info(f"📄 PDF geöffnet | seiten={gesamt_seiten} | datei={filename}")

    # Temporär in OneDrive speichern
    try:
        upload_to_onedrive(access_token, mailbox_email, "_TEMP", filename, pdf_bytes)
        logger.info(f"💾 Temp-Upload OK | pfad=_TEMP/{filename}")
    except Exception as e:
        logger.warning(f"⚠️ Temp-Upload fehlgeschlagen (nicht kritisch): {e}")

    # Mitarbeiter-Stammdaten laden
    stammdaten = []
    try:
        for ma_doc in db.collection("lohn_kunden").document(tenant_id).collection("mitarbeiter").stream():
            ma = ma_doc.to_dict()
            ma["id"] = ma_doc.id
            stammdaten.append(ma)
        logger.info(f"👥 Stammdaten geladen | anzahl={len(stammdaten)}")
    except Exception as e:
        logger.error(f"❌ Stammdaten-Fehler: {e}")

    # Seiten verarbeiten und nach Mitarbeiter gruppieren
    seiten_ergebnisse = []
    for i in range(gesamt_seiten):
        page = doc[i]
        page_num = i + 1
        try:
            info = process_page(page, page_num)
            seiten_ergebnisse.append(info)
            logger.info(f"  Seite {page_num}: typ={info.typ} | name={info.mitarbeiter_name or '–'} | pnr={info.personal_nr or '–'} | quelle={info.quelle} | validierung={info.validierung}")
        except Exception as e:
            logger.error(f"❌ Fehler Seite {page_num}: {e}", exc_info=True)
            fehler += 1
            seiten_details.append(SeitenDetail(
                seite=page_num, typ="fehler", status="fehler",
                quelle="", validierung="", fehler_details=str(e)
            ))

    # Nach Mitarbeiter gruppieren (mehrseitige Abrechnungen zusammenfassen)
    mitarbeiter_seiten: dict[str, list] = {}
    for info in seiten_ergebnisse:
        if not info.ist_lohnabrechnung:
            seiten_details.append(SeitenDetail(
                seite=info.seite, typ=info.typ, status="uebersprungen",
                quelle=info.quelle, validierung=info.validierung
            ))
            continue

        ma = match_mitarbeiter(info.personal_nr, info.mitarbeiter_name, stammdaten)

        if ma:
            key = ma.get("personal_nr") or ma.get("name")
            if key not in mitarbeiter_seiten:
                mitarbeiter_seiten[key] = {"ma": ma, "pages": [], "info": info}
            mitarbeiter_seiten[key]["pages"].append(info.seite)
            seiten_details.append(SeitenDetail(
                seite=info.seite, typ=info.typ, mitarbeiter_name=ma.get("name"),
                personal_nr=ma.get("personal_nr"), status="zugeordnet",
                quelle=info.quelle, validierung=info.validierung
            ))
            logger.info(f"  ✅ Zugeordnet: {info.mitarbeiter_name} → {ma.get('name')} (PNr: {ma.get('personal_nr')})")
        else:
            unklar += 1
            logger.warning(f"  ⚠️ Nicht zuordenbar: name={info.mitarbeiter_name} | pnr={info.personal_nr}")
            try:
                pdf_einzeln = create_single_pdf(doc, [info.seite])
                unklar_name = f"Unklar_{info.mitarbeiter_name.replace(' ', '_') + '_' if info.mitarbeiter_name else ''}Seite_{info.seite}_{filename}"
                upload_to_onedrive(access_token, mailbox_email, f"{onedrive_basispfad.strip('/')}/_Unklar", unklar_name, pdf_einzeln)
                logger.info(f"  💾 Unklar abgelegt: {unklar_name}")
            except Exception as e:
                logger.error(f"  ❌ Unklar-Upload fehlgeschlagen: {e}", exc_info=True)
            seiten_details.append(SeitenDetail(
                seite=info.seite, typ=info.typ, mitarbeiter_name=info.mitarbeiter_name,
                personal_nr=info.personal_nr, status="unklar",
                quelle=info.quelle, validierung=info.validierung,
                fehler_details="Kein passender Mitarbeiter in Stammdaten"
            ))

    # Pro Mitarbeiter: Einzel-PDF erzeugen, ablegen, Entwurf, Lexoffice
    for key, data in mitarbeiter_seiten.items():
        ma = data["ma"]
        pages = data["pages"]
        info = data["info"]
        ma_name = ma.get("name", "Unbekannt")
        ma_email = ma.get("email", "")
        ma_ordner = ma.get("onedrive_ordner", f"{onedrive_basispfad.strip('/')}/{ma_name.replace(' ', '_')}")
        monat = info.abrechnungsmonat or "unbekannt"

        try:
            pdf_einzeln = create_single_pdf(doc, pages)
            pdf_filename = generate_filename(ma_name, monat)
            erkannte += 1
            logger.info(f"  📄 Einzel-PDF erzeugt: {pdf_filename} | seiten={pages}")

            ordner_pfad = f"{ma_ordner.strip('/')}/Gehaltsabrechnungen"
            upload_result = upload_to_onedrive(access_token, mailbox_email, ordner_pfad, pdf_filename, pdf_einzeln)

            if not upload_result:
                fehler += 1
                logger.error(f"  ❌ OneDrive-Upload fehlgeschlagen: {ma_name}")
                try:
                    send_notification_email(access_token, mailbox_email,
                        f"OneDrive-Fehler: {ma_name}",
                        f"Die Gehaltsabrechnung für {ma_name} konnte nicht in OneDrive abgelegt werden.")
                except Exception as mail_err:
                    logger.error(f"  ❌ Fehler-Mail fehlgeschlagen: {mail_err}")
                continue

            logger.info(f"  ✅ OneDrive OK: {ordner_pfad}/{pdf_filename}")

            if ma_email:
                try:
                    monat_display = monat if monat != "unbekannt" else "den aktuellen Monat"
                    betreff = email_betreff.replace("{monat}", monat_display)
                    text = email_text.replace("{monat}", monat_display)
                    create_draft_email(access_token, mailbox_email, ma_email, betreff, text, pdf_einzeln, pdf_filename)
                    logger.info(f"  ✉️ Entwurf erstellt: {ma_email}")
                except Exception as e:
                    logger.error(f"  ❌ Entwurf-Fehler für {ma_name}: {e}", exc_info=True)
            else:
                logger.warning(f"  ⚠️ Keine E-Mail für {ma_name} — kein Entwurf erstellt")

            if lexoffice_api_key:
                try:
                    upload_to_lexoffice(lexoffice_api_key, pdf_einzeln, pdf_filename)
                    logger.info(f"  📤 Lexoffice OK: {pdf_filename}")
                except Exception as e:
                    logger.error(f"  ❌ Lexoffice-Fehler für {ma_name}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"  ❌ Unerwarteter Fehler bei {ma_name}: {e}", exc_info=True)
            fehler += 1

    if unklar > 0:
        try:
            send_notification_email(access_token, mailbox_email,
                f"{unklar} Abrechnung(en) nicht zugeordnet",
                f"Bei der Verarbeitung von '{filename}' konnten {unklar} Seite(n) keinem Mitarbeiter zugeordnet werden. "
                f"Die Dateien wurden unter /{onedrive_basispfad.strip('/')}/_Unklar abgelegt.")
        except Exception as e:
            logger.error(f"❌ Unklar-Benachrichtigung fehlgeschlagen: {e}")

    doc.close()

    try:
        delete_onedrive_file(access_token, mailbox_email, f"_TEMP/{filename}")
        logger.info(f"🗑️ Temp-Datei gelöscht: _TEMP/{filename}")
    except Exception as e:
        logger.warning(f"⚠️ Temp-Datei konnte nicht gelöscht werden: {e}")

    status = "success" if fehler == 0 and unklar == 0 else ("error" if erkannte == 0 else "partial")
    message = f"{erkannte} Mitarbeiter verarbeitet, {fehler} Fehler, {unklar} nicht zugeordnet"
    
    try:
        write_verarbeitungs_log(tenant_id, filename, gesamt_seiten, erkannte, fehler, unklar, status, message, seiten_details)
    except Exception as e:
        logger.error(f"❌ Log-Schreiben fehlgeschlagen: {e}", exc_info=True)

    logger.info(f"✅ PIPELINE FERTIG | status={status} | {message}")


# ==========================================
# 📝 VERARBEITUNGS-LOG
# ==========================================

def write_verarbeitungs_log(tenant_id: str, dateiname: str, gesamt_seiten: int,
                            erkannte: int, fehler: int, unklar: int,
                            status: str, message: str, seiten_details: list[SeitenDetail]):
    """Schreibt einen Verarbeitungs-Log-Eintrag in Firestore."""
    log_data = {
        "timestamp": firestore.SERVER_TIMESTAMP,
        "status": status,
        "dateiname": dateiname,
        "gesamt_seiten": gesamt_seiten,
        "erkannte_mitarbeiter": erkannte,
        "fehler_anzahl": fehler,
        "nicht_zugeordnet": unklar,
        "message": message,
        "seiten_details": [sd.model_dump() for sd in seiten_details]
    }
    db.collection("lohn_kunden").document(tenant_id).collection("verarbeitungs_logs").add(log_data)
    print(f"  📝 Log geschrieben: {status} — {message}")
