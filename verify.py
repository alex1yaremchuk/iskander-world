"""Structural checks against the actual indexed corpus."""
import json
import sqlite3
from inventory import ROOT, parse_fb2

db = sqlite3.connect(ROOT / 'data/inventory.sqlite')
assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
assert not db.execute('PRAGMA foreign_key_check').fetchall()
assert db.execute('SELECT COUNT(*) FROM SourceFile WHERE collection="canonical_10vol"').fetchone()[0] == 10
assert db.execute('SELECT COUNT(*) FROM SourceFile WHERE collection="alternate_fb2"').fetchone()[0] == 87
works = json.loads((ROOT / 'data/canonical_works.json').read_text(encoding='utf-8'))
assert len(works) == len({w['id'] for w in works})
assert len([w for w in works if w['kind'] == 'novel_chapter']) == 32
assert len([w for w in works if w['title'] == 'Утраты']) == 2
comparisons = json.loads((ROOT / 'data/edition_comparisons.json').read_text(encoding='utf-8'))
expected_links = {(m['work_id'],m['source_id'],m['location']) for m in comparisons if m['decision']=='normalized_text_identical'}
actual_links = set(db.execute("SELECT work_id,source_id,location FROM WorkSource WHERE review_note LIKE 'Full comparison text identical%'"))
assert actual_links == expected_links
assert all(db.execute('SELECT 1 FROM WorkFragment WHERE work_id=?',(w['id'],)).fetchone() for w in works)
for w in works:
    if 'source_id' in w:
        assert db.execute('SELECT COUNT(*) FROM WorkFragment WHERE work_id=?', (w['id'],)).fetchone()[0] > 0, w['title']
        assert db.execute('SELECT 1 FROM TocEntry WHERE id=? AND source_id=? AND location=?',
                          (w['toc_id'],w['source_id'],w['location'])).fetchone(), w['title']
# Inline styling must not break words; nesting must not duplicate story paragraphs.
xml = b'<FictionBook><description><title-info><book-title>Test</book-title></title-info></description><body><section><title><p>Part</p></title><p>A<strong>B</strong>C</p><section><p>Nested</p></section></section></body></FictionBook>'
_, _, fragments = parse_fb2(xml)
assert [f['text'] for f in fragments] == ['Part', 'ABC', 'Nested']
print('PASS: integrity, foreign keys, corpus counts, canonical source anchors, 32 chapters, homonyms, inline and nested FB2 text')
