"""Verify that the next-batch queue stays on the Mention side of entity resolution."""
import json
import sqlite3
from inventory import ROOT

db = sqlite3.connect(ROOT / 'data/inventory.sqlite')
db.row_factory = sqlite3.Row
batch = 'review_queue_chik_cycle_v1'
items = db.execute('SELECT * FROM ReviewItem WHERE batch_id=?', (batch,)).fetchall()
assert not db.execute('''SELECT i.id FROM ReviewItem i
  JOIN MentionResolution r ON r.mention_id=i.mention_id WHERE i.batch_id=?''', (batch,)).fetchall()
assert not db.execute('''SELECT i.id FROM ReviewItem i JOIN Mention m ON m.id=i.mention_id
  JOIN Appearance a ON a.work_id=m.work_id AND a.person_id=i.candidate_person_id
  WHERE i.batch_id=?''', (batch,)).fetchall()
for row in db.execute('''SELECT m.*,t.text FROM Mention m JOIN TextFragment t ON t.id=m.fragment_id
  WHERE m.run_id=?''', (batch,)):
    assert row['text'][row['start_char']:row['end_char']] == row['surface']
data = json.loads((ROOT / 'data/review_queue.json').read_text(encoding='utf-8'))
assert len(data['items']) == len(items) == data['summary']['candidate_count']
assert [x['title'] for x in data['summary']['works']] == [
    'Ночь и день Чика', 'Защита Чика', 'Чик и Пушкин',
    'Чик знал, где зарыта собака', 'Чик на охоте', 'Подвиг Чика',
    'Чик идет на оплакивание', 'Чик и лунатик', 'Чик — играющий судья',
    'Страшная месть Чика', 'Чик чтит обычаи', 'Чик и белая курица',
]
assert data['items'] and {x['status'] for x in data['items']} == {'pending'}
assert not db.execute('PRAGMA foreign_key_check').fetchall()
print('PASS: review queue spans, pending status, no premature entity resolution or appearances')
