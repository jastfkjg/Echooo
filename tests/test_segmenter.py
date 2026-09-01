from echooo.segmenter import SentenceSegmenter


def test_emits_complete_chinese_sentences_across_deltas() -> None:
    segmenter = SentenceSegmenter(min_chars=4)

    assert segmenter.feed("你好，这是") == []
    assert segmenter.feed("第一句。这是第二句！") == ["你好，这是第一句。", "这是第二句！"]
    assert segmenter.flush() == ""


def test_forces_a_chunk_when_text_has_no_punctuation() -> None:
    segmenter = SentenceSegmenter(min_chars=4, soft_chars=8, max_chars=10)

    assert segmenter.feed("一二三四五六七八九十十一") == ["一二三四五六七八九十"]
    assert segmenter.flush() == "十一"


def test_uses_a_long_comma_clause_as_a_soft_break() -> None:
    segmenter = SentenceSegmenter(min_chars=4, soft_chars=8, max_chars=30)

    assert segmenter.feed("这是一个足够长的分句，后面还有内容") == ["这是一个足够长的分句，"]
    assert segmenter.flush() == "后面还有内容"
