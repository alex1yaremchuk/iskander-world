"""Check the reproducible ledger of complete, context-preserving readings."""
import json
import sqlite3

from inventory import ROOT, digest


results = json.loads((ROOT / "context_reading_results.json").read_text(encoding="utf-8"))["works"]
assert results
assert len({item["title"] for item in results}) == len(results)
assert all(item["status"] == "read" for item in results)

db = sqlite3.connect(ROOT / "data" / "inventory.sqlite")
db.row_factory = sqlite3.Row
stored = {
    row["canonical_title"]: row
    for row in db.execute(
        """SELECT w.canonical_title, c.*
           FROM ContextReadingWork c JOIN Work w ON w.id=c.work_id"""
    )
}
assert set(stored) == {item["title"] for item in results}

for item in results:
    row = stored[item["title"]]
    expected_hash = digest(json.dumps(item, ensure_ascii=False, sort_keys=True))
    assert row["result_sha256"] == expected_hash, item["title"]
    assert row["narrator_id"] == item["narrator"]
    people = {entry["person"] for entry in item.get("appearances", [])}
    people.update(entry["id"] for entry in item.get("people", []))
    actual = {
        r[0]
        for r in db.execute(
            """SELECT a.person_id FROM Appearance a
               JOIN Work w ON w.id=a.work_id
               WHERE w.canonical_title=?""",
            (item["title"],),
        )
    }
    assert people <= actual, (item["title"], people - actual)
    for relation in item.get("relations", []):
        found = db.execute(
            """SELECT 1 FROM Relation r
               JOIN RelationEvidence re ON re.relation_id=r.id
               JOIN Evidence e ON e.id=re.evidence_id
               JOIN Work w ON w.id=e.work_id
               WHERE w.canonical_title=? AND r.from_person=?
                 AND r.to_person=? AND r.type=?""",
            (item["title"], relation["from"], relation["to"], relation["type"]),
        ).fetchone()
        assert found, (item["title"], relation)

print(f"PASS: {len(results)} complete contextual readings and their entities, relations, evidence, and hashes")
db.close()
