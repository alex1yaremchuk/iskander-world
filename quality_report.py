"""Create a compact, reproducible data-quality report from SQLite."""
import json
import sqlite3
from collections import Counter
from pathlib import Path

from inventory import ROOT


def rows(db, query, params=()):
    return [dict(r) for r in db.execute(query, params)]


def main():
    db = sqlite3.connect(ROOT / 'data/inventory.sqlite')
    db.row_factory = sqlite3.Row
    pilot = rows(db, '''SELECT w.id,w.canonical_title title,d.kind,
      COUNT(DISTINCT a.person_id) people
      FROM Work w JOIN WorkDetail d ON d.work_id=w.id
      JOIN Appearance a ON a.work_id=w.id AND a.id NOT LIKE 'bulk_%' AND a.id NOT LIKE 'deep_%' AND a.id NOT LIKE 'context_%'
      GROUP BY w.id ORDER BY json_extract(d.metadata_json,'$.volume'),w.canonical_title''')
    unresolved = rows(db, '''SELECT w.canonical_title work,COUNT(*) count
      FROM Mention m LEFT JOIN MentionResolution r ON r.mention_id=m.id
      JOIN Work w ON w.id=m.work_id
      WHERE m.run_id='pilot_v1' AND r.mention_id IS NULL
      GROUP BY m.work_id ORDER BY count DESC''')
    appearances = rows(db, '''SELECT p.canonical_name person,COUNT(*) works
      FROM Appearance a JOIN Person p ON p.id=a.person_id
      GROUP BY a.person_id ORDER BY works DESC,p.canonical_name''')
    relation_confidence = dict(db.execute('SELECT confidence,COUNT(*) FROM Relation GROUP BY confidence'))
    relation_status = dict(db.execute('SELECT status,COUNT(*) FROM Relation GROUP BY status'))
    report = {
        'metrics': {
            'verified_pilot_works': len(pilot),
            'context_read_works': db.execute("SELECT COUNT(*) FROM ContextReadingWork WHERE status='read'").fetchone()[0],
            'automatic_works': db.execute("SELECT COUNT(DISTINCT work_id) FROM Appearance WHERE id LIKE 'bulk_%'").fetchone()[0],
            'people': db.execute('SELECT COUNT(*) FROM Person').fetchone()[0],
            'aliases': db.execute('SELECT COUNT(*) FROM Alias').fetchone()[0],
            'verified_appearances': db.execute("SELECT COUNT(*) FROM Appearance WHERE id NOT LIKE 'bulk_%' AND id NOT LIKE 'deep_%' AND id NOT LIKE 'context_%'").fetchone()[0],
            'context_read_appearances': db.execute("""SELECT COUNT(*) FROM Appearance a
              JOIN ContextReadingWork c ON c.work_id=a.work_id
              WHERE a.id NOT LIKE 'bulk_%' AND a.id NOT LIKE 'deep_%'""").fetchone()[0],
            'deep_read_appearances': db.execute("SELECT COUNT(*) FROM Appearance WHERE id LIKE 'deep_%'").fetchone()[0],
            'automatic_appearances': db.execute("SELECT COUNT(*) FROM Appearance WHERE id LIKE 'bulk_%'").fetchone()[0],
            'verified_relations': db.execute("SELECT COUNT(*) FROM Relation WHERE id NOT LIKE 'bulk_%'").fetchone()[0],
            'automatic_relations': db.execute("SELECT COUNT(*) FROM Relation WHERE id LIKE 'bulk_%'").fetchone()[0],
            'places': db.execute('SELECT COUNT(*) FROM Place').fetchone()[0],
            'evidence': db.execute('SELECT COUNT(*) FROM Evidence').fetchone()[0],
            'pilot_mentions': db.execute("SELECT COUNT(*) FROM Mention WHERE run_id='pilot_v1'").fetchone()[0],
            'resolved_mentions': db.execute("SELECT COUNT(*) FROM MentionResolution r JOIN Mention m ON m.id=r.mention_id WHERE m.run_id='pilot_v1'").fetchone()[0],
            'review_queue': db.execute("SELECT COUNT(*) FROM ReviewItem WHERE batch_id='review_queue_v1'").fetchone()[0],
            'deep_relation_queue': db.execute("SELECT COUNT(*) FROM DeepReadItem WHERE item_type='relationship_context' AND priority=100").fetchone()[0],
            'canonical_works': db.execute('SELECT COUNT(*) FROM Work').fetchone()[0],
        },
        'pilot_works': pilot,
        'unresolved_mentions_by_work': unresolved,
        'appearances_per_person': appearances,
        'relations_by_confidence': relation_confidence,
        'relations_by_status': relation_status,
        'checks': {
            'foreign_key_violations': len(db.execute('PRAGMA foreign_key_check').fetchall()),
            'relations_without_evidence': db.execute('''SELECT COUNT(*) FROM Relation r
              LEFT JOIN RelationEvidence e ON e.relation_id=r.id WHERE e.relation_id IS NULL''').fetchone()[0],
            'people_without_evidence': db.execute("SELECT COUNT(*) FROM Person WHERE evidence_json IS NULL OR evidence_json='[]'").fetchone()[0],
            'appearances_without_evidence': db.execute("SELECT COUNT(*) FROM Appearance WHERE evidence_json IS NULL OR evidence_json='[]'").fetchone()[0],
            'resolved_queue_mentions': db.execute('''SELECT COUNT(*) FROM ReviewItem i
              JOIN MentionResolution r ON r.mention_id=i.mention_id
              WHERE i.batch_id='review_queue_v1' ''').fetchone()[0],
            'queue_appearances_created': db.execute('''SELECT COUNT(*) FROM ReviewItem i JOIN Mention m ON m.id=i.mention_id
              JOIN Appearance a ON a.work_id=m.work_id AND a.person_id=i.candidate_person_id
              WHERE i.batch_id='review_queue_v1' ''').fetchone()[0],
        },
    }
    out = ROOT / 'data/quality_report.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    m = report['metrics']; c = report['checks']
    lines = [
        '# Контроль качества данных', '',
        'Отчёт строится напрямую из SQLite после сборки пилота и очереди проверки.', '',
        '## Сводка', '',
        f"- Проверенный пилот: {m['verified_pilot_works']} из {m['canonical_works']} записей реестра; автоматический слой: {m['automatic_works']} произведений.",
        f"- Полностью прочитано с поддержанием контекста: {m['context_read_works']} произведений.",
        f"- Персонажей: {m['people']}; проверенных появлений: {m['verified_appearances']}; последовательным контекстным чтением: {m['context_read_appearances']}; найденных словарным проходом: {m['deep_read_appearances']}; широких автоматических кандидатов: {m['automatic_appearances']}.",
        f"- Проверенных связей: {m['verified_relations']}; автоматических совместных появлений: {m['automatic_relations']}; мест: {m['places']}.",
        f"- Mentions в пилоте: {m['pilot_mentions']}; разрешено: {m['resolved_mentions']}; ожидают решения: {m['pilot_mentions']-m['resolved_mentions']}.",
        f"- Приоритетная очередь контекстов отношений: {m['deep_relation_queue']} абзацев.",
        f"- Evidence-фрагментов: {m['evidence']}.", '',
        '## Покрытие пилота', '',
    ]
    for w in pilot:
        lines.append(f"- «{w['title']}» — {w['people']} персонажей.")
    lines += ['', '## Автоматические проверки', '',
              f"- Нарушения внешних ключей: {c['foreign_key_violations']}.",
              f"- Связи без evidence: {c['relations_without_evidence']}.",
              f"- Персонажи без evidence: {c['people_without_evidence']}.",
              f"- Появления без evidence: {c['appearances_without_evidence']}.",
              f"- Преждевременно разрешённые mentions очереди: {c['resolved_queue_mentions']}.",
              f"- Преждевременно созданные Appearance из очереди: {c['queue_appearances_created']}.", '',
              '## Неопределённость', '',
              '- Неразрешённые mentions допустимы и не считаются ошибкой.',
              '- Роль персонажа в произведении остаётся редакционной оценкой.',
              '- reported хранит слова героя или пересказ; rejected сохраняет опровергнутое утверждение, но не включает его в генеалогию.',
              '- Совпадения имени вне пилота остаются CorpusHit и не превращаются в Appearance.', '']
    (ROOT / 'QUALITY_REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    assert all(v == 0 for v in c.values()), c
    print(json.dumps({'metrics': m, 'checks': c}, ensure_ascii=False))
    db.close()


if __name__ == '__main__':
    main()
