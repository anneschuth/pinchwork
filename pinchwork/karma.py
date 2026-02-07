"""Moltbook karma verification service."""
import logging
from datetime import UTC, datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MOLTBOOK_API_BASE = "https://www.moltbook.com/api/v1"

# Karma thresholds for verification tiers
KARMA_VERIFIED_THRESHOLD = 100  # Minimum for verification badge
KARMA_PREMIUM_THRESHOLD = 500  # Premium tier
KARMA_ELITE_THRESHOLD = 1000  # Elite tier


async def fetch_moltbook_karma(
    handle: str, api_key: str | None = None
) -> Optional[int]:
    """
    Fetch karma score from Moltbook API.

    Currently calculates karma from post upvotes since the API doesn't
    expose a direct karma field. This is a best-effort approach.

    Args:
        handle: Moltbook username (without @)
        api_key: Optional Moltbook API key for authenticated requests

    Returns:
        Karma score (int) or None if not found/error
    """
    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient() as client:
            # Fetch user's posts to calculate karma from upvotes
            # Note: Moltbook API doesn't expose direct karma endpoint yet
            url = f"{MOLTBOOK_API_BASE}/posts?author={handle}&limit=100"
            resp = await client.get(url, headers=headers, timeout=10.0)

            if resp.status_code == 200:
                data = resp.json()
                posts = data.get("posts", [])

                # Calculate karma: sum of (upvotes - downvotes) across all posts
                karma = sum(
                    post.get("upvotes", 0) - post.get("downvotes", 0) for post in posts
                )

                logger.info(
                    f"Calculated karma for @{handle}: {karma} "
                    f"(from {len(posts)} posts)"
                )
                return karma

            elif resp.status_code == 404:
                logger.warning(f"Moltbook user @{handle} not found")
                return None
            else:
                logger.error(
                    f"Failed to fetch Moltbook data for @{handle}: "
                    f"{resp.status_code}"
                )
                return None

    except Exception as e:
        logger.error(f"Exception fetching karma for @{handle}: {e}")
        return None


def get_verification_tier(karma: int) -> str:
    """
    Return verification tier based on karma score.

    Tiers:
    - elite: 1000+ karma
    - premium: 500+ karma
    - verified: 100+ karma
    - unverified: <100 karma
    """
    if karma >= KARMA_ELITE_THRESHOLD:
        return "elite"
    elif karma >= KARMA_PREMIUM_THRESHOLD:
        return "premium"
    elif karma >= KARMA_VERIFIED_THRESHOLD:
        return "verified"
    else:
        return "unverified"


def get_bonus_credits(karma: int) -> int:
    """
    Calculate bonus starting credits based on karma tier.

    - Elite (1000+): +300 credits
    - Premium (500+): +200 credits
    - Verified (100+): +100 credits
    - Unverified (<100): +0 credits
    """
    tier = get_verification_tier(karma)

    bonuses = {
        "elite": 300,
        "premium": 200,
        "verified": 100,
        "unverified": 0,
    }

    return bonuses.get(tier, 0)


def get_tier_badge(verified: bool, karma: int | None) -> str:
    """
    Get badge emoji for verification tier.

    Returns:
        Badge string (emoji + text) or empty string if unverified
    """
    if not verified or karma is None:
        return ""

    tier = get_verification_tier(karma)
    badges = {
        "elite": "⭐ ELITE",
        "premium": "✨ PREMIUM",
        "verified": "✓ Verified",
    }

    return badges.get(tier, "")
