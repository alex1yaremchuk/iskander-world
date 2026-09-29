"""Fast, deliberately fallible whole-corpus character layer.

This is a coverage pass, not entity resolution.  It keeps the hand-read pilot
untouched and adds only explicitly marked automatic candidates with a literal
source fragment.  Re-running replaces this layer atomically.
"""
import json
import re
import sqlite3
from collections import Counter, defaultdict

from inventory import ROOT, digest

RUN_ID = 'bulk_v1'
NAME = re.compile(r'(?<![\w-])([А-ЯЁ][а-яё]{2,}(?:\s+[А-ЯЁ][а-яё]{2,}){1,2})(?![\w-])')
STOP = {
    'Это', 'Вот', 'Нет', 'Да', 'Как', 'Но', 'Что', 'Когда', 'Если', 'Или',
    'После', 'Перед', 'Тогда', 'Однако', 'Россия', 'Абхазия', 'Москва',
    'Мухус', 'Чегем', 'Грузия', 'Советский Союз', 'Великая Отечественная',
}


def norm(value):
    return value.replace('ё', 'е').casefold().strip()


def export(db):
    """Make the same browser projection as the pilot, including bulk rows."""
    def rows(table):
        return [dict(x) for x in db.execute('SELECT * FROM ' + table)]
    def parsed(items, column, target):
        for item in items:
            item[target] = json.loads(item.pop(column))
        return items

    people = parsed(rows('Person'), 'evidence_json', 'evidence')
    for person in people:
        person['mention_count'] = db.execute(
            'SELECT COUNT(*) FROM MentionResolution WHERE person_id=?', (person['id'],)
        ).fetchone()[0]
    relations = rows('Relation')
    for relation in relations:
        relation['evidence'] = [x[0] for x in db.execute(
            'SELECT evidence_id FROM RelationEvidence WHERE relation_id=?', (relation['id'],)
        )]
    appearances = parsed(rows('Appearance'), 'evidence_json', 'evidence')
    auto_work_ids = {x['work_id'] for x in appearances if x['id'].startswith('bulk_')}
    scanned_work_ids = {x[0] for x in db.execute('''SELECT DISTINCT wf.work_id FROM WorkFragment wf
        JOIN TextFragment t ON t.id=wf.fragment_id JOIN WorkDetail d ON d.work_id=wf.work_id
        JOIN SourceFile sf ON sf.source_id=t.source_id
        WHERE sf.collection='canonical_10vol' AND d.kind NOT IN ('novel','cycle')
          AND t.id NOT LIKE 'para_%' AND t.id NOT LIKE 'review_para_%'
          AND t.id NOT LIKE 'deep_para_%'
          AND t.id NOT LIKE 'deep_para_%' ''')}
    works = []
    for row in db.execute('''SELECT w.id,w.canonical_title,d.kind,d.parent_id,d.metadata_json
                             FROM Work w JOIN WorkDetail d ON d.work_id=w.id'''):
        meta = json.loads(row['metadata_json'])
        works.append(dict(id=row['id'], title=row['canonical_title'], kind=row['kind'],
                          parent_id=row['parent_id'], volume=meta.get('volume'),
                          pilot=row['id'] in {x['work_id'] for x in appearances
                                             if not x['id'].startswith(('bulk_', 'deep_'))},
                          automatic=row['id'] in scanned_work_ids,
                          automatic_candidates=row['id'] in auto_work_ids))
    data = dict(
        people=people, aliases=rows('Alias'), relations=relations, works=works,
        appearances=appearances, places=parsed(rows('Place'), 'evidence_json', 'evidence'),
        personPlaces=rows('PersonPlace'), evidence=rows('Evidence'), corpusHits=rows('CorpusHit'),
        meta=dict(pilot_count=sum(w['pilot'] for w in works),
                  automatic_work_count=len(scanned_work_ids), automatic_candidate_work_count=len(auto_work_ids),
                  person_count=len(people), relation_count=len(relations),
                  mention_count=db.execute('SELECT COUNT(*) FROM Mention').fetchone()[0],
                  unresolved_count=db.execute('''SELECT COUNT(*) FROM Mention m LEFT JOIN MentionResolution r
                                                  ON r.mention_id=m.id WHERE r.mention_id IS NULL''').fetchone()[0],
                  coverage='Проверенный пилот + линейное подробное чтение прозы + автоматические кандидаты.',
                  extraction='Ручной пилот; словарный проход известных героев; отдельная очередь отношений.'))
    (ROOT / 'data' / 'pilot_export.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT / 'site' / 'dist' / 'data.js').write_text('window.ISKANDER_DATA=' + json.dumps(data, ensure_ascii=False) + ';\n', encoding='utf-8')


def main():
    db = sqlite3.connect(ROOT / 'data' / 'inventory.sqlite')
    db.row_factory = sqlite3.Row
    # A source fragment can belong to several structural records; only leaves
    # are suitable for a work-level candidate appearance.
    source_rows = db.execute('''SELECT DISTINCT wf.work_id,t.id fragment_id,t.source_id,t.location,t.text
        FROM WorkFragment wf JOIN TextFragment t ON t.id=wf.fragment_id
        JOIN WorkDetail d ON d.work_id=wf.work_id JOIN SourceFile sf ON sf.source_id=t.source_id
        WHERE sf.collection='canonical_10vol' AND d.kind NOT IN ('novel','cycle')
          AND t.id NOT LIKE 'para_%' AND t.id NOT LIKE 'review_para_%'
    ''').fetchall()
    mentions = defaultdict(list)
    for row in source_rows:
        for match in NAME.finditer(row['text']):
            surface = match.group(1)
            if surface in STOP or surface.split()[0] in STOP:
                continue
            mentions[norm(surface)].append((surface, row, match.start(1), match.end(1)))

    # Require repetition inside a work or across works. This rejects most
    # sentence-initial noise while retaining recurring named characters.
    selected = {}
    for key, hits in mentions.items():
        by_work = Counter(x[1]['work_id'] for x in hits)
        if len(by_work) >= 2 or max(by_work.values()) >= 2:
            selected[key] = hits

    with db:
        rel_ids = [x[0] for x in db.execute("SELECT id FROM Relation WHERE id LIKE 'bulk_%'")]
        for rid in rel_ids:
            db.execute('DELETE FROM RelationEvidence WHERE relation_id=?', (rid,))
        db.execute("DELETE FROM Relation WHERE id LIKE 'bulk_%'")
        db.execute("DELETE FROM Appearance WHERE id LIKE 'bulk_%'")
        db.execute("DELETE FROM MentionResolution WHERE mention_id IN (SELECT id FROM Mention WHERE run_id=?)", (RUN_ID,))
        db.execute('DELETE FROM Mention WHERE run_id=?', (RUN_ID,))
        db.execute("DELETE FROM Evidence WHERE id LIKE 'bulk_%'")
        db.execute("DELETE FROM Person WHERE id LIKE 'bulk_%'")
        db.execute('DELETE FROM ExtractionRun WHERE id=?', (RUN_ID,))
        db.execute('INSERT INTO ExtractionRun VALUES (?,?,?)', (RUN_ID, 'bulk_named_groups', json.dumps({
            'scope': 'all canonical leaf works', 'rule': 'capitalized multiword groups repeated per work or corpus',
            'status': 'automatic candidates; not entity-resolved'}, ensure_ascii=False)))

        work_people = defaultdict(set)
        evidence_for = {}
        for key, hits in selected.items():
            pid = 'bulk_' + digest(key)[:24]
            canonical = Counter(x[0] for x in hits).most_common(1)[0][0]
            first_surface, row, start, end = hits[0]
            eid = 'bulk_ev_' + digest(pid + row['fragment_id'] + str(start))[:24]
            quote_left, quote_right = max(0, start - 180), min(len(row['text']), end + 280)
            db.execute('INSERT INTO Evidence VALUES (?,?,?,?,?,?,?,?,?)',
                       (eid, row['work_id'], row['source_id'], row['fragment_id'], row['text'][quote_left:quote_right],
                        quote_left, quote_right, row['location'], ''))
            db.execute('INSERT INTO Person VALUES (?,?,?,?,?,?)',
                       (pid, canonical, 'Автоматически выделенное имя; нуждается в редакционной проверке.',
                        'candidate', 'Автоматический слой: совпадение имени не доказывает тождество персонажа.', json.dumps([eid])))
            evidence_for[pid] = eid
            by_work = defaultdict(list)
            for surface, hit_row, hit_start, hit_end in hits:
                by_work[hit_row['work_id']].append((surface, hit_row, hit_start, hit_end))
            for wid, work_hits in by_work.items():
                surface, hit_row, hit_start, hit_end = work_hits[0]
                mid = 'bulk_men_' + digest(pid + wid + hit_row['fragment_id'] + str(hit_start))[:24]
                db.execute('INSERT INTO Mention VALUES (?,?,?,?,?,?,?,?,?)',
                           (mid, wid, hit_row['fragment_id'], hit_start, hit_end, surface, json.dumps([pid]),
                            'bulk_capitalized_name', RUN_ID))
                db.execute('INSERT INTO MentionResolution VALUES (?,?,?,?,?)',
                           (mid, pid, 'uncertain', eid, 'Автоматическое совпадение именной группы; требуется проверка.'))
                aid = 'bulk_app_' + digest(pid + wid)[:24]
                db.execute('INSERT INTO Appearance VALUES (?,?,?,?,?,?,?)',
                           (aid, pid, wid, 'mention', 'uncertain', json.dumps([eid]),
                            'Автоматический кандидат появления по повторяемому имени.'))
                work_people[wid].add(pid)

        # Deliberately do not create all person pairs inside a work.  That old
        # shortcut was quadratic and, more importantly, did not express an
        # actual relationship.  Explicit relationship contexts are collected
        # by deep_read.py and resolved separately.
        export(db)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    print('bulk candidates:', len(selected), 'works:', len(work_people))


if __name__ == '__main__':
    main()
