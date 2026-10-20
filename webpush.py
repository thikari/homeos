#!/usr/bin/env python3
"""Minimaler Web-Push-Versand (RFC 8291 aes128gcm + RFC 8292 VAPID) ohne pywebpush – braucht nur `cryptography`.

    keys = vapid_keys()                      # {"private": pem, "public": b64url}  → einmal erzeugen und speichern
    send(subscription, {"title": ..}, keys, sub="mailto:…")
"""
import os, json, time, base64, struct, urllib.request, urllib.parse
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.kdf.hkdf import HKDF, HKDFExpand
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def b64d(s): s = s.strip(); return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def vapid_keys():
    k = ec.generate_private_key(ec.SECP256R1())
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"private": pem, "public": b64u(pub)}

def _jwt(private_pem, aud, sub):
    k = serialization.load_pem_private_key(private_pem.encode(), None)
    h = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    c = b64u(json.dumps({"aud": aud, "exp": int(time.time()) + 12 * 3600, "sub": sub}, separators=(",", ":")).encode())
    der = k.sign(f"{h}.{c}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return f"{h}.{c}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"

def encrypt(plaintext: bytes, p256dh: str, auth: str):
    ua_pub = b64d(p256dh); auth_secret = b64d(auth)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub)
    as_key = ec.generate_private_key(ec.SECP256R1())
    as_pub = as_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = as_key.exchange(ec.ECDH(), ua_key)
    ikm = HKDF(hashes.SHA256(), 32, auth_secret, b"WebPush: info\x00" + ua_pub + as_pub).derive(shared)
    salt = os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    ct = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    return salt + struct.pack(">I", 4096) + bytes([len(as_pub)]) + as_pub + ct

def send(subscription: dict, payload: dict, keys: dict, sub="mailto:tafel@example.org", ttl=3600, urgency="normal"):
    """Liefert (status, text). 404/410 = Abo tot → löschen."""
    endpoint = subscription["endpoint"]
    body = encrypt(json.dumps(payload, ensure_ascii=False).encode(), subscription["keys"]["p256dh"], subscription["keys"]["auth"])
    u = urllib.parse.urlparse(endpoint)
    jwt = _jwt(keys["private"], f"{u.scheme}://{u.netloc}", sub)
    req = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": str(ttl), "Urgency": urgency,
        "Authorization": f"vapid t={jwt}, k={keys['public']}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:200]

# --- Selbsttest: Empfängerseite nachbauen und entschlüsseln ---
def _decrypt_as_ua(body: bytes, ua_priv, auth_secret: bytes):
    salt, rs, idlen = body[:16], body[16:20], body[20]
    as_pub = body[21:21 + idlen]; ct = body[21 + idlen:]
    ua_pub = ua_priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = ua_priv.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = HKDF(hashes.SHA256(), 32, auth_secret, b"WebPush: info\x00" + ua_pub + as_pub).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    return AESGCM(cek).decrypt(nonce, ct, None)[:-1]

if __name__ == "__main__":
    ua = ec.generate_private_key(ec.SECP256R1()); auth = os.urandom(16)
    p256dh = b64u(ua.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    body = encrypt(b'{"title":"Hallo"}', p256dh, b64u(auth))
    assert _decrypt_as_ua(body, ua, auth) == b'{"title":"Hallo"}'
    k = vapid_keys(); t = _jwt(k["private"], "https://web.push.apple.com", "mailto:x@y.z")
    assert t.count(".") == 2 and len(b64d(t.split(".")[2])) == 64
    print("webpush ok, public key", k["public"][:12] + "…")
