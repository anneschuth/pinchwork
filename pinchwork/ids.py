"""ID generation utilities."""

import secrets

from nanoid import generate

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
ID_LENGTH = 12


def gen_id(prefix: str) -> str:
    return f"{prefix}{generate(ALPHABET, ID_LENGTH)}"


def agent_id() -> str:
    return gen_id("ag_")


def task_id() -> str:
    return gen_id("tk_")


def bid_id() -> str:
    return gen_id("bd_")


def api_key() -> str:
    return f"pk_{secrets.token_urlsafe(24)}"


def ledger_id() -> str:
    return gen_id("le_")


def match_id() -> str:
    return gen_id("mt_")
