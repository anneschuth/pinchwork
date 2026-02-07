"""Tests for Moltbook karma verification."""

import pytest

from pinchwork.karma import (
    get_bonus_credits,
    get_tier_badge,
    get_verification_tier,
    validate_moltbook_handle,
)


def test_verification_tiers():
    """Test tier calculation based on karma."""
    assert get_verification_tier(50) == "unverified"
    assert get_verification_tier(99) == "unverified"
    assert get_verification_tier(100) == "verified"
    assert get_verification_tier(250) == "verified"
    assert get_verification_tier(500) == "premium"
    assert get_verification_tier(750) == "premium"
    assert get_verification_tier(1000) == "elite"
    assert get_verification_tier(5000) == "elite"


def test_bonus_credits():
    """Test bonus credit calculation."""
    assert get_bonus_credits(50) == 0
    assert get_bonus_credits(100) == 100
    assert get_bonus_credits(250) == 100
    assert get_bonus_credits(500) == 200
    assert get_bonus_credits(750) == 200
    assert get_bonus_credits(1000) == 300
    assert get_bonus_credits(5000) == 300


def test_tier_badges():
    """Test badge generation for tiers."""
    assert get_tier_badge(False, None) == ""
    assert get_tier_badge(False, 100) == ""
    assert get_tier_badge(True, None) == ""
    assert get_tier_badge(True, 50) == ""  # Unverified
    assert get_tier_badge(True, 100) == "✓ Verified"
    assert get_tier_badge(True, 500) == "✨ PREMIUM"
    assert get_tier_badge(True, 1000) == "⭐ ELITE"


def test_validate_handle_valid():
    """Test validation of valid handles."""
    assert validate_moltbook_handle("pinch") == "pinch"
    assert validate_moltbook_handle("@pinch") == "pinch"
    assert validate_moltbook_handle("  @pinch  ") == "pinch"
    assert validate_moltbook_handle("test_user") == "test_user"
    assert validate_moltbook_handle("user-123") == "user-123"
    assert validate_moltbook_handle("Agent_99") == "Agent_99"


def test_validate_handle_invalid():
    """Test validation rejects invalid handles."""
    # Empty
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_moltbook_handle("")
    
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_moltbook_handle("@")
    
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_moltbook_handle("   ")
    
    # Invalid characters
    with pytest.raises(ValueError, match="can only contain"):
        validate_moltbook_handle("user@example.com")
    
    with pytest.raises(ValueError, match="can only contain"):
        validate_moltbook_handle("user name")
    
    with pytest.raises(ValueError, match="can only contain"):
        validate_moltbook_handle("user!123")
    
    # Too long
    with pytest.raises(ValueError, match="too long"):
        validate_moltbook_handle("a" * 51)
