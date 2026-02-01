"""ID generation utilities."""

import secrets

from nanoid import generate

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
ID_LENGTH = 12


def gen_id(prefix: str) -> str:
    return f"{prefix}{generate(ALPHABET, ID_LENGTH)}"


def agent_id() -> str:
    return gen_id("ag-")


def task_id() -> str:
    return gen_id("tk-")


def api_key() -> str:
    return f"pwk-{secrets.token_urlsafe(32)}"


def ledger_id() -> str:
    return gen_id("le-")


def match_id() -> str:
    return gen_id("mt-")


def report_id() -> str:
    return gen_id("rp-")


def question_id() -> str:
    return gen_id("qa-")


def message_id() -> str:
    return gen_id("msg-")


def trust_id() -> str:
    return gen_id("tr-")


def referral_code() -> str:
    return f"ref-{secrets.token_urlsafe(12)}"
