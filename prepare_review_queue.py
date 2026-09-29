"""Build a durable review queue for the next Chik stories.

The queue contains Mention rows only. It deliberately creates no Person,
MentionResolution or Appearance records before a human/contextual pass.
"""
import csv
import io
import json
import re
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from inventory import ROOT, digest, local, text
from pilot_seed import PEOPLE


NEXT_TITLES = [
    'Ночь и день Чика',
    'Защита Чика',
    'Чик и Пушкин',
    'Чик знал, где зарыта собака',
    'Чик на охоте',
    'Подвиг Чика',
    'Чик идет на оплакивание',
    'Чик и лунатик',
    'Чик — играющий судья',
    'Страшная месть Чика',
    'Чик чтит обычаи',
    'Чик и белая курица',
]
RUN_ID = 'review_queue_chik_cycle_v1'


def paragraph_records(work, number):
    result = []
    with zipfile.ZipFile(ROOT / 'corpus' / work['source']) as book:
        for resource in work['resources']:
            body = ET.fromstring(book.read(resource)).find('.//{*}body')

            def walk(element, location):
                if local(element) == 'p':
                    value = text(element)
                    if value:
                        result.append({
                            'key': f'r{number}_{len(result)+1:04}',
                            'location': resource + '::' + location,
                            'resource': resource,
                            'text': value,
                        })
                    return
                for index, child in enumerate(element):
                    walk(child, f'{location}/{local(child)}[{index}]')

            walk(body, 'body')
    return result


def main():
    registry = json.loads((ROOT / 'data/canonical_works.json').read_text(encoding='utf-8'))
    works = []
    for number, title in enumerate(NEXT_TITLES, 1):
        work = next(dict(w) for w in registry if w['title'] == title and 'source' in w)
        work['paragraphs'] = paragraph_records(work, number)
        works.append(work)

    patterns = []
    for person in PEOPLE:
        if person['pattern']:
            patterns.append((person['id'], person['name'], re.compile(r'(?<!\w)(?:' + person['pattern'] + r')(?!\w)')))

    db = sqlite3.connect(ROOT / 'data/inventory.sqlite')
    db.executescript('''
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS ReviewBatch(
      id TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      method TEXT NOT NULL, scope_json TEXT NOT NULL, status TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS ReviewItem(
      id TEXT PRIMARY KEY, batch_id TEXT REFERENCES ReviewBatch(id),
      mention_id TEXT REFERENCES Mention(id), candidate_person_id TEXT REFERENCES Person(id),
      status TEXT NOT NULL, priority INTEGER NOT NULL, context TEXT NOT NULL, decision_note TEXT);
    CREATE INDEX IF NOT EXISTS review_status ON ReviewItem(batch_id,status,priority);
    ''')
    queue = []
    counts = defaultdict(Counter)
    with db:
        db.execute('DELETE FROM ReviewItem WHERE batch_id=?', (RUN_ID,))
        db.execute('DELETE FROM Mention WHERE run_id=?', (RUN_ID,))
        db.execute('DELETE FROM ExtractionRun WHERE id=?', (RUN_ID,))
        db.execute('DELETE FROM ReviewBatch WHERE id=?', (RUN_ID,))
        scope = [{'id': w['id'], 'title': w['title']} for w in works]
        metadata = {
            'scope': scope,
            'candidate_type': 'known_person_name_pattern',
            'entity_resolution': 'pending',
            'note': 'These are Mention candidates, never automatic Appearances.',
        }
        db.execute('INSERT INTO ExtractionRun VALUES (?,?,?)',
                   (RUN_ID, 'dictionary_candidate_queue', json.dumps(metadata, ensure_ascii=False)))
        db.execute('INSERT INTO ReviewBatch(id,method,scope_json,status) VALUES (?,?,?,?)',
                   (RUN_ID, 'known name patterns over paragraph fragments', json.dumps(scope, ensure_ascii=False), 'open'))

        for work_number, work in enumerate(works, 1):
            for ordinal, paragraph in enumerate(work['paragraphs']):
                fid = 'review_para_' + digest(work['source_id'] + ':' + paragraph['location'])
                raw = dict(paragraph, kind='review_paragraph', source_format='xhtml',
                           normalization='inline itertext joined; whitespace collapsed')
                db.execute('''INSERT INTO TextFragment VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET text=excluded.text,raw_json=excluded.raw_json''',
                    (fid, work['source_id'], 2000000 + ordinal, paragraph['location'], paragraph['text'],
                     digest(paragraph['text']), json.dumps(raw, ensure_ascii=False)))
                db.execute('INSERT OR IGNORE INTO WorkFragment VALUES (?,?)', (work['id'], fid))
                hits = []
                for person_id, person_name, pattern in patterns:
                    for match in pattern.finditer(paragraph['text']):
                        hits.append((match.start(), match.end(), match.group(), person_id, person_name))
                # Keep a full-name match instead of a shorter match over the same characters.
                seen = set()
                for start, end, surface, person_id, person_name in hits:
                    if any(a <= start and b >= end and b-a > end-start for a,b,_,_,_ in hits):
                        continue
                    # Several seed patterns can legitimately point to the same
                    # candidate.  A review row represents that span/candidate
                    # pair once, not once per matching regular expression.
                    marker = (start, end, person_id)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    mid = 'men_' + digest(f'{work["id"]}:{fid}:{start}:{end}')[:24]
                    context_start, context_end = max(0, start-140), min(len(paragraph['text']), end+220)
                    context = paragraph['text'][context_start:context_end]
                    db.execute('INSERT OR REPLACE INTO Mention VALUES (?,?,?,?,?,?,?,?,?)',
                               (mid, work['id'], fid, start, end, surface,
                                json.dumps([person_id]), 'review_name_candidate', RUN_ID))
                    # Batch is part of the durable identifier: the same span
                    # may be re-queued in a later, broader editorial pass.
                    item_id = 'review_' + digest(RUN_ID + ':' + mid + ':' + person_id)[:24]
                    priority = 100 if person_id in ('sandro','tengo','katya','brother_sandro','narrator') else 50
                    db.execute('INSERT INTO ReviewItem VALUES (?,?,?,?,?,?,?,NULL)',
                               (item_id, RUN_ID, mid, person_id, 'pending', priority, context))
                    queue.append({
                        'id': item_id, 'work_id': work['id'], 'work_title': work['title'],
                        'paragraph_key': paragraph['key'], 'location': paragraph['location'],
                        'mention_id': mid, 'surface': surface, 'candidate_person_id': person_id,
                        'candidate_person_name': person_name, 'status': 'pending',
                        'priority': priority, 'context': context,
                    })
                    counts[work['title']][person_name] += 1

    summary = {
        'batch_id': RUN_ID,
        'status': 'open',
        'works': [
            {
                'id': w['id'], 'title': w['title'], 'paragraph_count': len(w['paragraphs']),
                'candidate_count': sum(counts[w['title']].values()),
                'candidate_people': dict(counts[w['title']].most_common()),
            } for w in works
        ],
        'candidate_count': len(queue),
        'rule': 'A queue item is an unresolved Mention candidate, not a Person or Appearance.',
    }
    (ROOT / 'data/review_queue.json').write_text(
        json.dumps({'summary': summary, 'items': queue}, ensure_ascii=False, indent=2), encoding='utf-8')
    out = io.StringIO(newline='')
    fields = ['id','work_title','paragraph_key','location','surface','candidate_person_name','status','priority','context']
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
    writer.writeheader(); writer.writerows(queue)
    (ROOT / 'data/review_queue.csv').write_text(out.getvalue(), encoding='utf-8-sig')
    (ROOT / 'data/review_batch_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    db.close()
    # Keep the script usable from a legacy Windows console (cp1252), while the
    # JSON artifacts above retain their UTF-8 Russian text.
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    main()
