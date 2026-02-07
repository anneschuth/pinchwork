"""Moltbook karma verification service."""

import asyncio
import logging
import re

import httpx

logger = logging.getLogger(__name__)

MOLTBOOK_API_BASE = "https://www.moltbook.com/api/v1"

# Karma thresholds for verification tiers
KARMA_VERIFIED_THRESHOLD = 100  # Minimum for verification badge
KARMA_PREMIUM_THRESHOLD = 500  # Premium tier
KARMA_ELITE_THRESHOLD = 1000  # Elite tier

# Compiled regex for handle validation (performance)
_HANDLE_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_moltbook_handle(handle: str) -> str:
    """
    Validate and normalize a Moltbook handle.

    Args:
        handle: Raw handle input (may include @)

    Returns:
        Normalized handle (no @, stripped)

    Raises:
        ValueError: If handle is invalid
    """
    if not handle:
        raise ValueError("Moltbook handle is required")

    # Strip whitespace FIRST, then @ prefix (order matters!)
    normalized = handle.strip().lstrip("@")

    # Check not empty after normalization
    if not normalized:
        raise ValueError("Moltbook handle cannot be empty")

    # Validate format: alphanumeric, underscore, hyphen only
    if not _HANDLE_PATTERN.match(normalized):
        raise ValueError(
            "Moltbook handle can only contain letters, numbers, underscores, and hyphens"
        )

    # Check length
    if len(normalized) > 50:
        raise ValueError("Moltbook handle too long (max 50 characters)")

    return normalized


async def fetch_moltbook_karma(handle: str, api_key: str | None = None) -> int | None:
    """
    Fetch karma score from Moltbook API with timeout protection.

    Currently calculates karma from post upvotes since the API doesn't
    expose a direct karma field. This is a best-effort approach.

    Args:
        handle: Moltbook username (without @, already validated)
        api_key: Optional Moltbook API key for authenticated requests

    Returns:
        Karma score (int) or None if not found/error/timeout
    """
    try:
        # Hard timeout to prevent registration hangs
        async with asyncio.timeout(3.0):
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            async with httpx.AsyncClient() as client:
                # Fetch user's posts to calculate karma from upvotes
                # Note: Moltbook API doesn't expose direct karma endpoint yet
                url = f"{MOLTBOOK_API_BASE}/posts?author={handle}&limit=100"
                # Inner timeout lower than outer (2.5s < 3.0s outer timeout)
                resp = await client.get(url, headers=headers, timeout=2.5)

                if resp.status_code == 200:
                    data = resp.json()
                    posts = data.get("posts", [])

                    # Calculate karma: sum of (upvotes - downvotes) across all posts
                    karma = sum(post.get("upvotes", 0) - post.get("downvotes", 0) for post in posts)

                    logger.info(
                        f"Calculated karma for @{handle}: {karma} (from {len(posts)} posts)"
                    )
                    return karma

                elif resp.status_code == 404:
                    logger.warning(f"Moltbook user @{handle} not found")
                    return None
                else:
                    logger.error(f"Failed to fetch Moltbook data for @{handle}: {resp.status_code}")
                    return None

    except TimeoutError:
        logger.warning(f"Timeout fetching karma for @{handle} (>3s)")
        return None
    except Exception as e:
        logger.error(f"Exception fetching karma for @{handle}: {e}")
        return None


def get_verification_tier(karma: int) -> str:
    """
    Return verification tier based on karma score.

    Tiers:
    - Elite: 1000+ karma
    - Premium: 500+ karma
    - Verified: 100+ karma
    - Unverified: <100 karma
    """
    if karma >= KARMA_ELITE_THRESHOLD:
        return "Elite"
    elif karma >= KARMA_PREMIUM_THRESHOLD:
        return "Premium"
    elif karma >= KARMA_VERIFIED_THRESHOLD:
        return "Verified"
    else:
        return "Unverified"


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
        "Elite": "⭐ ELITE",
        "Premium": "✨ PREMIUM",
        "Verified": "✓ Verified",
    }

    return badges.get(tier, "")
