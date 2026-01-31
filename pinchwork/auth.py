"""Authentication: bcrypt hashing with fingerprint-based DB lookup."""

from __future__ import annotations

import hashlib

import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pinchwork.database import get_db_session
from pinchwork.db_models import Agent


def hash_key(key: str) -> str:
    return bcrypt.hashpw(key.encode(), bcrypt.gensalt()).decode()


def verify_key(key: str, key_hash: str) -> bool:
    return bcrypt.checkpw(key.encode(), key_hash.encode())


def key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


async def get_current_agent(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> Agent:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    raw_key = auth[7:]
    fp = key_fingerprint(raw_key)

    result = await session.execute(select(Agent).where(Agent.key_fingerprint == fp))
    agent = result.scalar_one_or_none()

    if not agent or not verify_key(raw_key, agent.key_hash):
        raise HTTPException(status_code=401, detail="Invalid API key")

    return agent


AuthAgent = Depends(get_current_agent)
