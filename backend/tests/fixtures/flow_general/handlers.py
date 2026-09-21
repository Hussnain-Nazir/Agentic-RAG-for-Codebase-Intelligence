from workers import hash_pw, store_user


def register_user(password: str) -> str:
    hashed = hash_pw(password)
    return store_user(hashed)
