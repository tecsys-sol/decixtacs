"""SHA-512 crypt(3) hashes for tac_plus-ng ``password login = crypt ...``."""

from passlib.hash import sha512_crypt


def tacacs_crypt(password: str) -> str:
    return sha512_crypt.using(rounds=656000).hash(password)


def tacacs_verify(password: str, hashed: str) -> bool:
    return sha512_crypt.verify(password, hashed)
