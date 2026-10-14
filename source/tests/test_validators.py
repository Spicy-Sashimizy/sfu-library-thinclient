"""Tests for validators module."""

from lib.validators import (
    sanitize_search_query,
    sanitize_search_query_advanced,
)


class TestSanitizeSearchQuery:
    def test_normal_query_unchanged(self):
        result = sanitize_search_query("machine learning")
        assert result == "machine learning"

    def test_strips_html_tags(self):
        result = sanitize_search_query("<script>alert('xss')</script>machine learning")
        assert "<script>" not in result
        assert "alert" in result

    def test_removes_null_bytes(self):
        result = sanitize_search_query("machine\x00learning")
        assert "\x00" not in result
        assert "machine" in result

    def test_truncates_oversized_input(self):
        long_query = "a" * 2000
        result = sanitize_search_query(long_query)
        assert len(result) <= 1000

    def test_empty_query(self):
        result = sanitize_search_query("")
        assert result == ""

    def test_collapses_whitespace(self):
        result = sanitize_search_query("  machine   learning  ")
        assert result == "machine learning"

    def test_preserves_quotes_and_ampersands(self):
        result = sanitize_search_query('query & "test"')
        assert '&' in result
        assert '"test"' in result

    def test_preserves_phrase_quotes(self):
        result = sanitize_search_query('"machine learning"')
        assert result == '"machine learning"'

    def test_preserves_boolean_operators(self):
        result = sanitize_search_query('"CRISPR" AND "sickle cell"')
        assert result == '"CRISPR" AND "sickle cell"'

    def test_preserves_wildcards(self):
        result = sanitize_search_query("cultur*")
        assert result == "cultur*"
        result2 = sanitize_search_query("wom?n")
        assert result2 == "wom?n"

    def test_strips_dangerous_chars(self):
        result = sanitize_search_query("<script>alert('xss')</script>test")
        assert "<script>" not in result
        assert "test" in result
        result2 = sanitize_search_query("test\x00query")
        assert "\x00" not in result2

    def test_max_boolean_operators(self):
        terms = " AND ".join([f"term{i}" for i in range(36)])
        result = sanitize_search_query_advanced(terms)
        assert result.count(" AND ") <= 30

    def test_non_ascii_preserved(self):
        result = sanitize_search_query("recherche en français")
        assert "français" in result
