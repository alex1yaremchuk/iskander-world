"""Check the reproducible ledger of complete, context-preserving readings."""
import json
import sqlite3

from inventory import ROOT, digest
from apply_stateful_reading import canonical_person_id


results = json.loads((ROOT / "context_reading_results.json").read_text(encoding="utf-8"))["works"]
assert results
def result_key(item):
    return item.get("work_id") or item["title"]


assert len({result_key(item) for item in results}) == len(results)
assert all(item["status"] == "read" for item in results)

db = sqlite3.connect(ROOT / "data" / "inventory.sqlite")
db.row_factory = sqlite3.Row
stored = {
    row["work_id"]: row
    for row in db.execute(
        """SELECT w.canonical_title, c.*
           FROM ContextReadingWork c JOIN Work w ON w.id=c.work_id"""
    )
}
works_by_title = {}
for row in db.execute("SELECT id,canonical_title,rowid FROM Work ORDER BY rowid"):
    works_by_title.setdefault(row["canonical_title"], row["id"])
expected_ids = {item.get("work_id") or works_by_title[item["title"]] for item in results}
assert set(stored) == expected_ids

for item in results:
    work_id = item.get("work_id") or works_by_title[item["title"]]
    row = stored[work_id]
    expected_hash = digest(json.dumps(item, ensure_ascii=False, sort_keys=True))
    assert row["result_sha256"] == expected_hash, item["title"]
    assert row["narrator_id"] == canonical_person_id(item["narrator"])
    people = {canonical_person_id(entry["person"]) for entry in item.get("appearances", [])}
    people.update(canonical_person_id(entry["id"]) for entry in item.get("people", []))
    actual = {
        r[0]
        for r in db.execute(
            """SELECT a.person_id FROM Appearance a
               WHERE a.work_id=?""",
            (work_id,),
        )
    }
    assert people <= actual, (item["title"], people - actual)
    rejected = {canonical_person_id(entry["person"]) for entry in item.get("rejected_appearances", [])}
    assert not (rejected & actual), (item["title"], "rejected appearances remain", rejected & actual)
    for relation in item.get("relations", []):
        found = db.execute(
            """SELECT 1 FROM Relation r
               JOIN RelationEvidence re ON re.relation_id=r.id
               JOIN Evidence e ON e.id=re.evidence_id
               WHERE e.work_id=? AND r.from_person=?
                 AND r.to_person=? AND r.type=?""",
            (work_id, canonical_person_id(relation["from"]), canonical_person_id(relation["to"]), relation["type"]),
        ).fetchone()
        assert found, (item["title"], relation)

people_ids = {row[0] for row in db.execute("SELECT id FROM Person")}
assert "chik_mother" in people_ids
assert not ({"narrator_mother", "kama_big_house"} & people_ids)
assert "vakhtang_bochua" in people_ids
assert "bulk_b5ece0029482484dd2c243d2" not in people_ids
assert db.execute(
    "SELECT count(*) FROM Person WHERE canonical_name='Вахтанг Бочуа'"
).fetchone()[0] == 1
assert db.execute(
    "SELECT 1 FROM Relation WHERE from_person='chik' AND to_person='narrator' AND type='same_person'"
).fetchone()

kozlotur_work = db.execute(
    "SELECT id FROM Work WHERE canonical_title='Созвездие Козлотура'"
).fetchone()
assert kozlotur_work
assert db.execute(
    """SELECT 1 FROM Appearance
       WHERE work_id=? AND person_id='narrator' AND role='main'""",
    (kozlotur_work[0],),
).fetchone()
assert "Созвездия Козлотура" in db.execute(
    "SELECT description FROM Person WHERE id='narrator'"
).fetchone()[0]

print(f"PASS: {len(results)} complete contextual readings and their entities, relations, evidence, and hashes")
db.close()
