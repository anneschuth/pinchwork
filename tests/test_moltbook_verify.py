"""Tests for Moltbook verification service."""

from unittest.mock import patch

import pytest

from pinchwork.db_models import Agent
from pinchwork.services.moltbook_verify import (
    _extract_post_id,
    _get_bonus_credits,
    verify_moltbook_post,
)


def test_extract_post_id():
    """Test post ID extraction from various URL formats."""
    # Valid URLs
    assert _extract_post_id("https://www.moltbook.com/post/abc123-def456") == "abc123-def456"
    assert _extract_post_id("https://moltbook.com/post/xyz789") == "xyz789"
    assert _extract_post_id("http://www.moltbook.com/post/test-id-123") == "test-id-123"

    # Invalid URLs
    assert _extract_post_id("not-a-url") is None
    assert _extract_post_id("https://example.com/post/123") is None
    assert _extract_post_id("https://www.moltbook.com/posts/123") is None  # plural
    assert _extract_post_id("") is None


def test_get_bonus_credits():
    """Test bonus credit calculation for different karma tiers."""
    assert _get_bonus_credits(0) == 0
    assert _get_bonus_credits(50) == 0
    assert _get_bonus_credits(99) == 0
    assert _get_bonus_credits(100) == 100  # Verified
    assert _get_bonus_credits(250) == 100  # Verified
    assert _get_bonus_credits(499) == 100  # Verified
    assert _get_bonus_credits(500) == 200  # Premium
    assert _get_bonus_credits(750) == 200  # Premium
    assert _get_bonus_credits(999) == 200  # Premium
    assert _get_bonus_credits(1000) == 300  # Elite
    assert _get_bonus_credits(5000) == 300  # Elite


@pytest.mark.asyncio
async def test_verify_already_verified(db):
    """Test that already-verified agents can't verify again."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle="testuser",
            verified=True,
            moltbook_karma=150,
            verification_tier="Verified",
        )
        session.add(agent)
        await session.commit()

        result = await verify_moltbook_post(session, agent, "https://www.moltbook.com/post/test-id")

        assert result["success"] is False
        assert "Already verified" in result["error"]


@pytest.mark.asyncio
async def test_verify_no_moltbook_handle(db):
    """Test that agents without Moltbook handle can't verify."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle=None,
            verified=False,
        )
        session.add(agent)
        await session.commit()

        result = await verify_moltbook_post(session, agent, "https://www.moltbook.com/post/test-id")

        assert result["success"] is False
        assert "No Moltbook handle set" in result["error"]


@pytest.mark.asyncio
async def test_verify_invalid_url(db):
    """Test that invalid post URLs are rejected."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle="testuser",
            verified=False,
        )
        session.add(agent)
        await session.commit()

        result = await verify_moltbook_post(session, agent, "https://example.com/not-moltbook")

        assert result["success"] is False
        assert "Invalid Moltbook post URL" in result["error"]


@pytest.mark.asyncio
async def test_verify_post_not_found(db):
    """Test handling of post not found."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle="testuser",
            verified=False,
        )
        session.add(agent)
        await session.commit()

        with patch("pinchwork.services.moltbook_verify._fetch_moltbook_post") as mock_fetch:
            mock_fetch.return_value = None

            result = await verify_moltbook_post(
                session, agent, "https://www.moltbook.com/post/nonexistent"
            )

            assert result["success"] is False
            assert "Post not found" in result["error"]


@pytest.mark.asyncio
async def test_verify_author_mismatch(db):
    """Test that post author must match agent's Moltbook handle."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle="testuser",
            verified=False,
        )
        session.add(agent)
        await session.commit()

        mock_post = {
            "author": {"name": "different_user"},
            "content": "some content with ref-test",
        }

        with patch("pinchwork.services.moltbook_verify._fetch_moltbook_post") as mock_fetch:
            mock_fetch.return_value = mock_post

            result = await verify_moltbook_post(
                session, agent, "https://www.moltbook.com/post/test-id"
            )

            assert result["success"] is False
            assert "doesn't match your Moltbook handle" in result["error"]


@pytest.mark.asyncio
async def test_verify_missing_referral_code(db):
    """Test that post content must contain referral code."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle="testuser",
            verified=False,
        )
        session.add(agent)
        await session.commit()

        mock_post = {
            "author": {"name": "testuser"},
            "content": "some content without the code",
        }

        with patch("pinchwork.services.moltbook_verify._fetch_moltbook_post") as mock_fetch:
            mock_fetch.return_value = mock_post

            result = await verify_moltbook_post(
                session, agent, "https://www.moltbook.com/post/test-id"
            )

            assert result["success"] is False
            assert "doesn't contain your referral code" in result["error"]


@pytest.mark.asyncio
async def test_verify_success_verified_tier(db):
    """Test successful verification with Verified tier (100-499 karma)."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle="testuser",
            verified=False,
        )
        session.add(agent)
        await session.commit()

        mock_post = {
            "author": {"name": "testuser"},
            "content": "Join Pinchwork! curl ... 'referral': 'ref-test' ...",
        }

        with (
            patch("pinchwork.services.moltbook_verify._fetch_moltbook_post") as mock_fetch,
            patch("pinchwork.services.moltbook_verify.fetch_moltbook_karma") as mock_karma,
        ):
            mock_fetch.return_value = mock_post
            mock_karma.return_value = 250  # Verified tier

            result = await verify_moltbook_post(
                session, agent, "https://www.moltbook.com/post/test-id"
            )

            assert result["success"] is True
            assert result["verified"] is True
            assert result["karma"] == 250
            assert result["tier"] == "Verified"
            assert result["bonus_credits"] == 100
            assert result["total_credits"] == 200  # 100 base + 100 bonus

            # Check agent was updated
            await db.refresh(agent)
            assert agent.verified is True
            assert agent.moltbook_karma == 250
            assert agent.verification_tier == "Verified"
            assert agent.credits == 200


@pytest.mark.asyncio
async def test_verify_success_premium_tier(db):
    """Test successful verification with Premium tier (500-999 karma)."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle="testuser",
            verified=False,
        )
        session.add(agent)
        await session.commit()

        mock_post = {
            "author": {"name": "testuser"},
            "content": "Join Pinchwork! curl ... 'referral': 'ref-test' ...",
        }

        with (
            patch("pinchwork.services.moltbook_verify._fetch_moltbook_post") as mock_fetch,
            patch("pinchwork.services.moltbook_verify.fetch_moltbook_karma") as mock_karma,
        ):
            mock_fetch.return_value = mock_post
            mock_karma.return_value = 600  # Premium tier

            result = await verify_moltbook_post(
                session, agent, "https://www.moltbook.com/post/test-id"
            )

            assert result["success"] is True
            assert result["karma"] == 600
            assert result["tier"] == "Premium"
            assert result["bonus_credits"] == 200
            assert result["total_credits"] == 300  # 100 base + 200 bonus


@pytest.mark.asyncio
async def test_verify_success_elite_tier(db):
    """Test successful verification with Elite tier (1000+ karma)."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle="testuser",
            verified=False,
        )
        session.add(agent)
        await session.commit()

        mock_post = {
            "author": {"name": "testuser"},
            "content": "Join Pinchwork! curl ... 'referral': 'ref-test' ...",
        }

        with (
            patch("pinchwork.services.moltbook_verify._fetch_moltbook_post") as mock_fetch,
            patch("pinchwork.services.moltbook_verify.fetch_moltbook_karma") as mock_karma,
        ):
            mock_fetch.return_value = mock_post
            mock_karma.return_value = 1500  # Elite tier

            result = await verify_moltbook_post(
                session, agent, "https://www.moltbook.com/post/test-id"
            )

            assert result["success"] is True
            assert result["karma"] == 1500
            assert result["tier"] == "Elite"
            assert result["bonus_credits"] == 300
            assert result["total_credits"] == 400  # 100 base + 300 bonus


@pytest.mark.asyncio
async def test_verify_case_insensitive_author(db):
    """Test that author matching is case-insensitive."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle="TestUser",  # Mixed case
            verified=False,
        )
        session.add(agent)
        await session.commit()

        mock_post = {
            "author": {"name": "testuser"},  # lowercase
            "content": "Join Pinchwork! curl ... 'referral': 'ref-test' ...",
        }

        with (
            patch("pinchwork.services.moltbook_verify._fetch_moltbook_post") as mock_fetch,
            patch("pinchwork.services.moltbook_verify.fetch_moltbook_karma") as mock_karma,
        ):
            mock_fetch.return_value = mock_post
            mock_karma.return_value = 200

            result = await verify_moltbook_post(
                session, agent, "https://www.moltbook.com/post/test-id"
            )

            assert result["success"] is True  # Should match despite case difference


@pytest.mark.asyncio
async def test_verify_karma_fetch_fails(db):
    """Test handling of karma fetch failure (returns None)."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle="testuser",
            verified=False,
        )
        session.add(agent)
        await session.commit()

        mock_post = {
            "author": {"name": "testuser"},
            "content": "Join Pinchwork! curl ... 'referral': 'ref-test' ...",
        }

        with (
            patch("pinchwork.services.moltbook_verify._fetch_moltbook_post") as mock_fetch,
            patch("pinchwork.services.moltbook_verify.fetch_moltbook_karma") as mock_karma,
        ):
            mock_fetch.return_value = mock_post
            mock_karma.return_value = None  # API failure

            result = await verify_moltbook_post(
                session, agent, "https://www.moltbook.com/post/test-id"
            )

            assert result["success"] is False
            assert "Failed to fetch your karma" in result["error"]


@pytest.mark.asyncio
async def test_verify_below_threshold(db):
    """Test that verification is blocked below 100 karma threshold."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-test",
            moltbook_handle="testuser",
            verified=False,
        )
        session.add(agent)
        await session.commit()

        mock_post = {
            "author": {"name": "testuser"},
            "content": "Join Pinchwork! curl ... 'referral': 'ref-test' ...",
        }

        with (
            patch("pinchwork.services.moltbook_verify._fetch_moltbook_post") as mock_fetch,
            patch("pinchwork.services.moltbook_verify.fetch_moltbook_karma") as mock_karma,
        ):
            mock_fetch.return_value = mock_post
            mock_karma.return_value = 50  # Below threshold

            result = await verify_moltbook_post(
                session, agent, "https://www.moltbook.com/post/test-id"
            )

            assert result["success"] is False
            assert "requires at least 100 karma" in result["error"]
            assert result["karma"] == 50


@pytest.mark.asyncio
async def test_verify_referral_substring_no_match(db):
    """Test that referral code uses word boundary (prevents substring false positives)."""
    async with db() as session:
        agent = Agent(
            id="ag-test",
            name="TestAgent",
            key_hash="hash",
            key_fingerprint="fp",
            credits=100,
            referral_code="ref-abc123",
            moltbook_handle="testuser",
            verified=False,
        )
        session.add(agent)
        await session.commit()

        # Post contains ref-abc12345 which CONTAINS ref-abc123 but shouldn't match
        mock_post = {
            "author": {"name": "testuser"},
            "content": "Join Pinchwork! curl ... 'referral': 'ref-abc12345' ...",
        }

        with patch("pinchwork.services.moltbook_verify._fetch_moltbook_post") as mock_fetch:
            mock_fetch.return_value = mock_post

            result = await verify_moltbook_post(
                session, agent, "https://www.moltbook.com/post/test-id"
            )

            assert result["success"] is False
            assert "doesn't contain your referral code" in result["error"]
