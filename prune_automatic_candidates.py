"""Remove unresolved automatic name candidates after editorial reconciliation.

``bulk_extract.py`` is intentionally permissive: it finds repeated capitalized
word groups so that a later pass can discover missed names.  Those rows are a
review substrate, not public character cards.  ``reconcile_people.py`` first
folds every confirmed or exact-name match into an editorial identity.  This
step then audits and removes the residual ``bulk_*`` identities.

The audit also records every editorial person without a meaningful relation.
Such rows are not automatically deleted: a one-scene person, named animal,
collective, or historical reference can be real even when no edge has yet been
asserted.  Keeping this distinction prevents a cleanup rule from erasing valid
reading results.
"""
import json
import sqlite3
from pathlib import Path

from bulk_extract import export
from inventory import ROOT


AUDIT_JSON = ROOT / "data" / "automatic_name_audit.json"
AUDIT_MARKDOWN = ROOT / "AUTOMATIC_NAME_AUDIT.md"


def work_titles(db, person_id):
    return [row[0] for row in db.execute(
        """SELECT DISTINCT w.canonical_title
           FROM Appearance a JOIN Work w ON w.id=a.work_id
           WHERE a.person_id=? ORDER BY w.canonical_title""",
        (person_id,),
    )]


def first_evidence(db, person):
    evidence_ids = json.loads(person["evidence_json"] or "[]")
    if not evidence_ids:
        return None
    row = db.execute(
        """SELECT e.id,e.quote,e.location,w.canonical_title work_title
           FROM Evidence e LEFT JOIN Work w ON w.id=e.work_id WHERE e.id=?""",
        (evidence_ids[0],),
    ).fetchone()
    return dict(row) if row else None


def has_meaningful_relation(db, person_id):
    return bool(db.execute(
        """SELECT 1 FROM Relation
           WHERE status IN ('accepted','reported')
             AND (from_person=? OR to_person=?) LIMIT 1""",
        (person_id, person_id),
    ).fetchone())


def audit_record(db, person, decision, reason):
    return {
        "id": person["id"],
        "name": person["canonical_name"],
        "kind": person["kind"],
        "decision": decision,
        "reason": reason,
        "works": work_titles(db, person["id"]),
        "evidence": first_evidence(db, person),
    }


def write_audit(records, removed_count, kept_count):
    payload = {
        "scope": "union of residual automatic candidates and editorial people without accepted/reported relations",
        "rule": {
            "remove": "residual bulk_* candidate after confirmed reconciliation; automatic extraction alone is not an identity",
            "keep": "editorially/contextually established entity; absence of an asserted relation is not evidence of extraction noise",
        },
        "summary": {
            "reviewed": len(records),
            "removed_automatic_candidates": removed_count,
            "kept_editorial_without_relations": kept_count,
        },
        "records": records,
    }
    AUDIT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Аудит автоматически выделенных имён и персонажей без связей",
        "",
        f"Проверено записей: **{len(records)}**. Удалено сырых автоматических "
        f"кандидатов: **{removed_count}**. Сохранено редакторских сущностей без "
        f"связей: **{kept_count}**.",
        "",
        "Автоматическая карточка удаляется, если после склейки подтверждённых "
        "совпадений она всё ещё имеет идентификатор `bulk_*`: такой результат "
        "фиксирует только повторившуюся группу слов с прописной буквы. "
        "Редакторская карточка без связи сохраняется, когда цитата подтверждает "
        "реального одноэпизодного персонажа, животное, коллектив или историческое "
        "упоминание.",
        "",
        "## Удалённые автоматические кандидаты",
        "",
    ]
    removed = [x for x in records if x["decision"] == "remove"]
    kept = [x for x in records if x["decision"] == "keep"]
    for item in sorted(removed, key=lambda x: x["name"].casefold()):
        works = "; ".join(item["works"]) or "—"
        lines.append(f"- **{item['name']}** (`{item['id']}`) — {works}")
    lines.extend(["", "## Сохранённые редакторские сущности без связей", ""])
    for item in sorted(kept, key=lambda x: x["name"].casefold()):
        works = "; ".join(item["works"]) or "—"
        lines.append(f"- **{item['name']}** (`{item['id']}`, {item['kind']}) — {works}")
    lines.append("")
    AUDIT_MARKDOWN.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def referenced_evidence_ids(db):
    result = set()
    for table in ("Person", "Appearance"):
        for row in db.execute(f"SELECT evidence_json FROM {table}"):
            result.update(json.loads(row[0] or "[]"))
    for table, column in (
        ("Alias", "evidence_id"),
        ("MentionResolution", "evidence_id"),
        ("PersonPlace", "evidence_id"),
        ("CorpusHit", "evidence_id"),
        ("RelationEvidence", "evidence_id"),
    ):
        result.update(row[0] for row in db.execute(
            f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"
        ))
    return result


def main():
    db = sqlite3.connect(ROOT / "data" / "inventory.sqlite")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    bulk_people = db.execute(
        "SELECT * FROM Person WHERE id LIKE 'bulk_%' ORDER BY canonical_name"
    ).fetchall()
    assert not db.execute(
        """SELECT id FROM Relation WHERE status IN ('accepted','reported')
           AND (from_person LIKE 'bulk_%' OR to_person LIKE 'bulk_%')"""
    ).fetchall(), "A related automatic identity must be reconciled manually, not pruned"

    editorial_zero = [
        person for person in db.execute(
            "SELECT * FROM Person WHERE id NOT LIKE 'bulk_%' ORDER BY canonical_name"
        )
        if not has_meaningful_relation(db, person["id"])
    ]
    records = [
        audit_record(
            db, person, "remove",
            "Unresolved automatic capitalized-word candidate after confirmed identity reconciliation; no meaningful relations.",
        )
        for person in bulk_people
    ]
    records.extend(
        audit_record(
            db, person, "keep",
            "Editorial/context-reading entity supported by a source citation; no meaningful relation is currently asserted.",
        )
        for person in editorial_zero
    )
    write_audit(records, len(bulk_people), len(editorial_zero))

    bulk_ids = {person["id"] for person in bulk_people}
    bulk_evidence = {
        evidence_id
        for person in bulk_people
        for evidence_id in json.loads(person["evidence_json"] or "[]")
    }
    with db:
        # Each residual bulk mention originally has one candidate.  Delete only
        # those spans; mentions already redirected to a verified identity stay.
        mention_ids = [
            row["id"] for row in db.execute("SELECT id,candidates_json FROM Mention")
            if bulk_ids.intersection(json.loads(row["candidates_json"] or "[]"))
        ]
        for mention_id in mention_ids:
            db.execute("DELETE FROM ReviewItem WHERE mention_id=?", (mention_id,))
            db.execute("DELETE FROM CorpusHit WHERE mention_id=?", (mention_id,))
            db.execute("DELETE FROM MentionResolution WHERE mention_id=?", (mention_id,))
            db.execute("DELETE FROM Mention WHERE id=?", (mention_id,))

        for person_id in bulk_ids:
            db.execute("DELETE FROM ReviewItem WHERE candidate_person_id=?", (person_id,))
            db.execute("DELETE FROM CorpusHit WHERE person_id=?", (person_id,))
            db.execute("DELETE FROM PersonPlace WHERE person_id=?", (person_id,))
            db.execute("DELETE FROM Alias WHERE person_id=?", (person_id,))
            db.execute("DELETE FROM Appearance WHERE person_id=?", (person_id,))
            db.execute("DELETE FROM MentionResolution WHERE person_id=?", (person_id,))
            db.execute("DELETE FROM Person WHERE id=?", (person_id,))

        referenced = referenced_evidence_ids(db)
        for evidence_id in bulk_evidence - referenced:
            db.execute("DELETE FROM Evidence WHERE id=?", (evidence_id,))

    export(db)
    assert not db.execute("SELECT 1 FROM Person WHERE id LIKE 'bulk_%'").fetchone()
    assert not db.execute("PRAGMA foreign_key_check").fetchall()
    db.close()
    print(
        f"Audited {len(records)} names: removed {len(bulk_people)} residual automatic "
        f"candidates; kept {len(editorial_zero)} editorial entities without relations."
    )


if __name__ == "__main__":
    main()
