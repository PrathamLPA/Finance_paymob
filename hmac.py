import hashlib

secret = "6975BF6AEDCCC3BACA2497A12283336A"

fingerprint = hashlib.sha256(secret.encode()).hexdigest()[:8]

print(fingerprint)