"""Sentence splitting tests."""

from __future__ import annotations

from jarvis.agent.loop import _split_sentences


def test_basic():
    sentences, remainder = _split_sentences("Hello world. How are you? Good")
    assert sentences == ["Hello world.", "How are you?"]
    assert remainder == " Good"


def test_no_end():
    sentences, remainder = _split_sentences("Hello world")
    assert sentences == []
    assert remainder == "Hello world"


def test_multiple():
    sentences, remainder = _split_sentences("A. B! C? D")
    assert sentences == ["A.", "B!", "C?"]
    assert remainder == " D"


def test_empty():
    sentences, remainder = _split_sentences("")
    assert sentences == []
    assert remainder == ""


def test_newline():
    sentences, remainder = _split_sentences("First line\nSecond line\nPartial")
    assert len(sentences) == 2
    assert sentences[0] == "First line"
    assert sentences[1] == "Second line"
    assert remainder == "Partial"
