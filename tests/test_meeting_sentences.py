import pytest

from echooo.meeting_sentences import sentences, expand_evidence


def row(i, text, start):
    return dict(id=str(i), recording_id='r', speaker='Alice', content=text,
                start_ms=start, end_ms=start+100, created_at=i)


def test_speech_order_not_late_repair_insertion_order_and_cross_fragment_quotes():
    rows = [row(1, 'release on', 100), row(2, 'Wednesday.', 200), row(3, 'We', 0)]
    unit, = sentences(rows)
    assert unit['content'] == 'We release on Wednesday.'
    assert unit['complete']
    proof = expand_evidence([{'utterance_id':unit['id'], 'quote':'release on Wednesday.'}], [unit])
    assert proof == [{'utterance_id':'1','quote':'release on'}, {'utterance_id':'2','quote':'Wednesday.'}]
    rows[1]['content'] = 'Thursday.'
    assert sentences(rows)[0]['version'] != unit['version']


def test_incomplete_and_speaker_boundaries():
    rows = [row(1, 'We need to', 0), row(2, 'assign an owner.', 100)]
    assert not sentences(rows[:1])[0]['complete']
    assert sentences(rows)[0]['complete']
    rows[1]['speaker'] = 'Bob'
    assert len(sentences(rows)) == 2


def test_mandarin_and_invalid_evidence():
    unit, = sentences([row(1,'计划周三',0), row(2,'发布。',100)])
    assert unit['content'] == '计划周三发布。'
    with pytest.raises(ValueError):
        expand_evidence([{'utterance_id':unit['id'],'quote':'计划周五发布。'}], [unit])
