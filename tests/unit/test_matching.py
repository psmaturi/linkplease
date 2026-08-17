"""
tests/unit/test_matching.py — Unit tests for keyword matching logic.

Tests the find_matching_rules function in isolation by mocking the DB.

IMPORTANT CASES:
- Case-insensitive match (PRICE, price, Price all match "price" rule)
- Keyword anywhere in comment (not just at start)
- Multiple rules can match a single comment
- Empty comment text returns no matches
- Non-matching comment returns empty list
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.matching_service import find_matching_rules


def make_rule(keyword: str, dm_message: str = "test message", rule_id: str = "rule_1"):
    """Create a mock Rule object."""
    rule = MagicMock()
    rule.id = rule_id
    rule.keyword = keyword.lower()  # stored lowercase in DB
    rule.dm_message = dm_message
    return rule


class TestFindMatchingRules:
    @pytest.mark.asyncio
    async def test_exact_keyword_matches(self):
        """A comment containing the exact keyword should match."""
        mock_db = AsyncMock()
        price_rule = make_rule("price")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [price_rule]
        mock_db.execute = AsyncMock(return_value=mock_result)

        matches = await find_matching_rules("I want to know the price", mock_db)
        assert len(matches) == 1
        assert matches[0].keyword == "price"

    @pytest.mark.asyncio
    async def test_uppercase_comment_matches_lowercase_rule(self):
        """PRICE in comment should match 'price' rule (case-insensitive)."""
        mock_db = AsyncMock()
        price_rule = make_rule("price")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [price_rule]
        mock_db.execute = AsyncMock(return_value=mock_result)

        matches = await find_matching_rules("PRICE?", mock_db)
        assert len(matches) == 1

    @pytest.mark.asyncio
    async def test_keyword_anywhere_in_comment(self):
        """Keyword can be in the middle or end of comment."""
        mock_db = AsyncMock()
        link_rule = make_rule("link")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [link_rule]
        mock_db.execute = AsyncMock(return_value=mock_result)

        matches = await find_matching_rules("send me the link please", mock_db)
        assert len(matches) == 1

    @pytest.mark.asyncio
    async def test_multiple_rules_can_match(self):
        """A single comment can match multiple rules."""
        mock_db = AsyncMock()
        price_rule = make_rule("price", rule_id="rule_1")
        link_rule = make_rule("link", rule_id="rule_2")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [price_rule, link_rule]
        mock_db.execute = AsyncMock(return_value=mock_result)

        matches = await find_matching_rules("PRICE and also the link please", mock_db)
        assert len(matches) == 2

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self):
        """Comment with no matching keyword returns empty list."""
        mock_db = AsyncMock()
        price_rule = make_rule("price")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [price_rule]
        mock_db.execute = AsyncMock(return_value=mock_result)

        matches = await find_matching_rules("Great photo!", mock_db)
        assert matches == []

    @pytest.mark.asyncio
    async def test_empty_comment_returns_empty(self):
        """None or empty comment text returns no matches."""
        mock_db = AsyncMock()
        matches = await find_matching_rules("", mock_db)
        assert matches == []

        matches = await find_matching_rules(None, mock_db)
        assert matches == []

    @pytest.mark.asyncio
    async def test_no_rules_configured(self):
        """If there are no rules, no matches."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        matches = await find_matching_rules("PRICE", mock_db)
        assert matches == []

    @pytest.mark.asyncio
    async def test_partial_keyword_match(self):
        """
        'price' keyword should match comments where 'price' appears embedded
        in a word (e.g., 'overpriced') because it's a substring match.
        Note: 'price' is NOT in 'pricing' (p-r-i-c-i-n-g vs p-r-i-c-e).
        """
        mock_db = AsyncMock()
        price_rule = make_rule("price")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [price_rule]
        mock_db.execute = AsyncMock(return_value=mock_result)

        # "overpriced" contains the substring "price" → should match
        matches = await find_matching_rules("that seems overpriced", mock_db)
        assert len(matches) == 1
