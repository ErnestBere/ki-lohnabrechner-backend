import os
from google.cloud import firestore
from cryptography.fernet import Fernet
import requests
import json

db = firestore.Client()
fernet = Fernet(os.environ.get('ENCRYPTION_KEY', 'x_zY5d-vP7B1wHkZqL2m_tO3fJ6uI8eN4cR9vM1bV0Q='))

def decrypt(data):
    return fernet.decrypt(data.encode()).decode()

docs = db.collection('lohn_kunden').limit(1).stream()
for doc in docs:
    data = doc.to_dict()
    enc_key = data.get('lexoffice_api_key')
    if enc_key:
        api_key = decrypt(enc_key)
        res = requests.get('https://api.lexware.io/v1/posting-categories', headers={'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'})
        categories = res.json()
        print('Total categories:', len(categories))
        for c in categories:
            if 'lohn' in c.get('name', '').lower() or 'gehalt' in c.get('name', '').lower():
                print(c)
