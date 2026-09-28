import securelib


def hash_pw(password: str) -> str:
    return securelib.digest(password)


def store_user(value: str) -> str:
    return value
