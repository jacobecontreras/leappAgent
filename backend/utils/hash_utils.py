import hashlib

CHUNK_SIZE = 1024 * 1024


def sha256_file(file_path: str) -> str:
    """Compute the SHA-256 of a file in chunks"""
    digest = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
