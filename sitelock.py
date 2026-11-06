"""Passwortschutz für die ganze Seite.

Die Daten der Seite (data.json und der in index.html eingebettete Stand) werden mit AES-256-GCM verschlüsselt.
Der Schlüssel kommt per PBKDF2 aus dem Passwort im Secret SITE_PASSWORT. Ohne Passwort enthält die Seite
keine lesbaren Inhalte. Das Salz hängt nur am Repository, damit ein Gerät, das einmal entsperrt wurde,
auch die stündlichen neuen Stände ohne erneute Eingabe öffnen kann (bis das Passwort geändert wird).
"""
import base64
import hashlib
import json
import os

ITERATIONS = 600_000


def _key(password, salt):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode())


def salt_for(repo):
    return hashlib.sha256(("mego-news-site/" + (repo or "")).encode()).digest()[:16]


_cache = {}


def key_for(password, repo):
    k = (password, repo)
    if k not in _cache:
        _cache[k] = _key(password, salt_for(repo))
    return _cache[k]


def seal(text, generated, password, repo):
    """Verschlüsselter Umschlag. Nur der Zeitstempel bleibt lesbar (für die Prüfung, ob die Seite aktuell ist)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = os.urandom(12)
    ct = AESGCM(key_for(password, repo)).encrypt(iv, text.encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"lock": 1, "generated": generated, "iter": ITERATIONS, "salt": b64(salt_for(repo)), "iv": b64(iv), "ct": b64(ct)}


def unseal(env, password, repo):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt = base64.b64decode(env["salt"])
    key = (key_for(password, repo) if salt == salt_for(repo) and env.get("iter") == ITERATIONS else
           PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=env["iter"]).derive(password.encode()))
    plain = AESGCM(key).decrypt(base64.b64decode(env["iv"]), base64.b64decode(env["ct"]), None)
    return json.loads(plain)
