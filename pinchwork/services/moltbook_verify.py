"""Moltbook verification service."""

from __future__ import annotations

import re

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from pinchwork.db_models import Agent
from pinchwork.karma import fetch_moltbook_karma, get_verification_tier


async def verify_moltbook_post(
    session: AsyncSession,
    agent: Agent,
    post_url: str,
) -> dict[str, any]:
    """
    Verify agent's Moltbook account by checking their post.

    Process:
    1. Extract post ID from URL
    2. Fetch post from Moltbook API
    3. Verify author matches agent.moltbook_handle
    4. Verify post contains agent.referral_code
    5. Re-fetch current karma (not stale registration karma!)
    6. Calculate bonus based on current karma
    7. Award credits and set verified=True

    Returns:
        dict with success/error and details
    """
    # Already verified?
    if agent.verified:
        return {
            "success": False,
            "verified": True,
            "error": "Already verified",
            "karma": agent.moltbook_karma,
            "tier": agent.verification_tier,
        }

    # Must have moltbook_handle set
    if not agent.moltbook_handle:
        return {
            "success": False,
            "error": "No Moltbook handle set. Use PATCH /v1/me to add your handle first.",
        }

    # Extract post ID from URL
    post_id = _extract_post_id(post_url)
    if not post_id:
        return {
            "success": False,
            "error": "Invalid Moltbook post URL. Expected format: https://www.moltbook.com/post/{id}",
        }

    # Fetch post from Moltbook
    try:
        post_data = await _fetch_moltbook_post(post_id)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to fetch post from Moltbook: {str(e)}",
        }

    if not post_data:
        return {
            "success": False,
            "error": (
                "Post not found on Moltbook. Make sure the post is public and the URL is "
                "correct. If you just posted it, wait a few seconds and try again."
            ),
        }

    # Verify author matches
    author_name = post_data.get("author", {}).get("name", "")
    if author_name.lower() != agent.moltbook_handle.lower():
        return {
            "success": False,
            "error": (
                f"Post author (@{author_name}) doesn't match your Moltbook handle "
                f"(@{agent.moltbook_handle})"
            ),
        }

    # Verify referral code in content (with word boundary to prevent substring matches)
    content = post_data.get("content", "")
    if not re.search(rf"\b{re.escape(agent.referral_code)}\b", content):
        return {
            "success": False,
            "error": (
                f"Post doesn't contain your referral code ({agent.referral_code}). "
                "Make sure you include the full curl command with your referral code."
            ),
        }

    # Re-fetch CURRENT karma (not registration karma!)
    # This encourages building karma before verifying
    current_karma = await fetch_moltbook_karma(agent.moltbook_handle)

    # Handle karma fetch failure
    if current_karma is None:
        return {
            "success": False,
            "error": (
                "Failed to fetch your karma from Moltbook. The API might be temporarily "
                "unavailable. Please try again in a few moments."
            ),
        }

    # Check minimum threshold
    if current_karma < 100:
        return {
            "success": False,
            "error": (
                f"Your Moltbook karma is {current_karma}, but verification requires at "
                "least 100 karma. Keep engaging on Moltbook and try again when you reach 100+!"
            ),
            "karma": current_karma,
        }

    tier = get_verification_tier(current_karma)
    bonus_credits = _get_bonus_credits(current_karma)

    # Award bonus and set verified
    from datetime import UTC, datetime

    agent.moltbook_karma = current_karma
    agent.verification_tier = tier
    agent.verified = True
    agent.credits += bonus_credits
    agent.karma_verified_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(agent)

    return {
        "success": True,
        "verified": True,
        "karma": current_karma,
        "tier": tier,
        "bonus_credits": bonus_credits,
        "total_credits": agent.credits,
        "message": (
            f"✓ Verified! Karma: {current_karma} → {tier} tier → +{bonus_credits} credits bonus"
        ),
    }


def _extract_post_id(url: str) -> str | None:
    """Extract Moltbook post ID from URL."""
    # Match: https://www.moltbook.com/post/{id} or https://moltbook.com/post/{id}
    pattern = r"https?://(?:www\.)?moltbook\.com/post/([\w-]+)"
    match = re.match(pattern, url.strip())
    return match.group(1) if match else None


async def _fetch_moltbook_post(post_id: str) -> dict | None:
    """Fetch post from Moltbook API."""
    from pinchwork.config import settings

    url = f"https://www.moltbook.com/api/v1/posts/{post_id}"
    headers = {}
    if settings.moltbook_api_key:
        headers["Authorization"] = f"Bearer {settings.moltbook_api_key}"

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                # API returns {"success": true, "post": {...}}
                return data.get("post")
            return None
        except Exception:
            raise


def _get_bonus_credits(karma: int) -> int:
    """Calculate bonus credits based on karma tier."""
    if karma >= 1000:
        return 300  # Elite
    elif karma >= 500:
        return 200  # Premium
    elif karma >= 100:
        return 100  # Verified
    return 0  # Below threshold
