"""Materialize results of sequential context-preserving reading."""
import json
import sqlite3

from bulk_extract import export
from deep_read import paragraphs
from inventory import ROOT, digest


def main():
    results = json.loads((ROOT / "context_reading_results.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "data" / "canonical_works.json").read_text(encoding="utf-8"))
    db = sqlite3.connect(ROOT / "data" / "inventory.sqlite")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("""CREATE TABLE IF NOT EXISTS ContextReadingWork(
      work_id TEXT PRIMARY KEY REFERENCES Work(id), status TEXT, narrator_id TEXT,
      summary TEXT, narrator_note TEXT, result_sha256 TEXT,
      updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    with db:
        for result in results["works"]:
            work = next(
                w for w in registry
                if w.get("source") and (
                    w["id"] == result.get("work_id")
                    if result.get("work_id")
                    else w["title"] == result["title"]
                )
            )
            ps = paragraphs(work)
            evidence_cache = {}

            def evidence(needle):
                if needle in evidence_cache:
                    return evidence_cache[needle]
                found = [(i, resource, value) for i, (resource, value) in enumerate(ps, 1) if needle in value]
                assert len(found) == 1, (result["title"], needle, len(found))
                ordinal, resource, value = found[0]
                fid = "state_para_" + digest(work["id"] + ":" + str(ordinal))[:24]
                location = resource + "::p" + str(ordinal)
                db.execute("INSERT INTO TextFragment VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET text=excluded.text",
                           (fid, work["source_id"], 5000000 + ordinal, location, value, digest(value),
                            json.dumps({"kind": "stateful_reading"}, ensure_ascii=False)))
                db.execute("INSERT OR IGNORE INTO WorkFragment VALUES (?,?)", (work["id"], fid))
                start = value.index(needle)
                eid = "state_ev_" + digest(work["id"] + ":" + needle)[:24]
                db.execute("INSERT INTO Evidence VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET quote=excluded.quote,start_char=excluded.start_char,end_char=excluded.end_char",
                           (eid, work["id"], work["source_id"], fid, needle, start, start + len(needle), location, ""))
                evidence_cache[needle] = eid
                return eid

            entities = [{"id": a["person"], "role": a["role"], "evidence": a["evidence"]}
                        for a in result.get("appearances", [])]

            # A complete reading can disprove a name-only hit from an earlier
            # automatic pass (for example, «Машина» mistaken for «Маша»).
            for rejected in result.get("rejected_appearances", []):
                db.execute(
                    "DELETE FROM Appearance WHERE person_id=? AND work_id=?",
                    (rejected["person"], work["id"]),
                )

            def merge_person(old_id, new_id):
                """Fold a disposable bulk-extraction identity into a read identity."""
                if old_id == new_id:
                    return
                old = db.execute("SELECT evidence_json,notes FROM Person WHERE id=?", (old_id,)).fetchone()
                if not old:
                    return
                new = db.execute("SELECT evidence_json,notes FROM Person WHERE id=?", (new_id,)).fetchone()
                assert new, (old_id, new_id)
                merged_evidence = list(dict.fromkeys(json.loads(new[0]) + json.loads(old[0])))
                merged_notes = " ".join(x for x in [new[1] or "", old[1] or ""] if x).strip()
                db.execute("UPDATE Person SET evidence_json=?,notes=? WHERE id=?",
                           (json.dumps(merged_evidence), merged_notes, new_id))
                # The complete-reading appearance below supersedes a bulk row in this work.
                db.execute("DELETE FROM Appearance WHERE person_id=? AND work_id=?", (old_id, work["id"]))
                for old_app in db.execute("SELECT * FROM Appearance WHERE person_id=?", (old_id,)).fetchall():
                    new_app = db.execute(
                        "SELECT * FROM Appearance WHERE person_id=? AND work_id=?",
                        (new_id, old_app["work_id"]),
                    ).fetchone()
                    if new_app:
                        combined = list(dict.fromkeys(
                            json.loads(new_app["evidence_json"]) + json.loads(old_app["evidence_json"])
                        ))
                        db.execute("UPDATE Appearance SET evidence_json=? WHERE id=?",
                                   (json.dumps(combined), new_app["id"]))
                        db.execute("DELETE FROM Appearance WHERE id=?", (old_app["id"],))
                    else:
                        db.execute("UPDATE Appearance SET person_id=? WHERE id=?", (new_id, old_app["id"]))
                for table, column in [
                    ("Alias", "person_id"), ("MentionResolution", "person_id"),
                    ("PersonPlace", "person_id"),
                    ("CorpusHit", "person_id"), ("ReviewItem", "candidate_person_id"),
                ]:
                    db.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (new_id, old_id))
                db.execute("UPDATE Relation SET from_person=? WHERE from_person=?", (new_id, old_id))
                db.execute("UPDATE Relation SET to_person=? WHERE to_person=?", (new_id, old_id))
                db.execute("DELETE FROM Person WHERE id=?", (old_id,))

            for p in result.get("people", []):
                eids = [evidence(x) for x in p["evidence"]]
                old = db.execute("SELECT evidence_json FROM Person WHERE id=?", (p["id"],)).fetchone()
                if old:
                    eids = list(dict.fromkeys(json.loads(old[0]) + eids))
                    db.execute("UPDATE Person SET canonical_name=?,description=?,evidence_json=? WHERE id=?",
                               (p["name"], p["description"], json.dumps(eids), p["id"]))
                else:
                    db.execute("INSERT INTO Person VALUES (?,?,?,?,?,?)",
                               (p["id"], p["name"], p["description"], p.get("kind", "character"),
                                "Последовательно прочитанный контекст произведения.", json.dumps(eids)))
                for old_id in p.get("merge_ids", []):
                    merge_person(old_id, p["id"])
                entities.append({"id": p["id"], "role": p["role"], "evidence": p["evidence"]})

            for entity in entities:
                eids = [evidence(x) for x in entity["evidence"]]
                appearances = db.execute(
                    """SELECT * FROM Appearance WHERE person_id=? AND work_id=?
                       ORDER BY CASE WHEN id LIKE 'bulk_%' THEN 1 ELSE 0 END, id""",
                    (entity["id"], work["id"]),
                ).fetchall()
                if appearances:
                    aid = appearances[0]["id"]
                    all_evidence = list(dict.fromkeys(
                        eids + [eid for row in appearances for eid in json.loads(row["evidence_json"])]
                    ))
                    rank = {"mention": 0, "episode": 1, "secondary": 2, "main": 3}
                    role = max([entity["role"]] + [row["role"] for row in appearances], key=lambda x: rank.get(x, 0))
                    db.execute(
                        "UPDATE Appearance SET role=?,confidence='explicit',evidence_json=?,rationale=? WHERE id=?",
                        (role, json.dumps(all_evidence),
                         "Участие подтверждено последовательным чтением всего произведения.", aid),
                    )
                    db.executemany("DELETE FROM Appearance WHERE id=?", [(row["id"],) for row in appearances[1:]])
                else:
                    db.execute("INSERT INTO Appearance VALUES (?,?,?,?,?,?,?)",
                               ("state_app_" + digest(entity["id"] + ":" + work["id"])[:24], entity["id"],
                                work["id"], entity["role"], "explicit", json.dumps(eids),
                                "Участие подтверждено последовательным чтением всего произведения."))

            for relation in result.get("relations", []):
                existing = db.execute(
                    """SELECT id FROM Relation
                       WHERE from_person=? AND to_person=? AND type=? AND status!='rejected'
                       ORDER BY CASE WHEN id LIKE 'state_rel_%' THEN 1 ELSE 0 END, id LIMIT 1""",
                    (relation["from"], relation["to"], relation["type"]),
                ).fetchone()
                if existing:
                    rid = existing[0]
                else:
                    rid = "state_rel_" + digest(relation["from"] + ":" + relation["to"] + ":" + relation["type"])[:24]
                    db.execute("INSERT INTO Relation VALUES (?,?,?,?,?,?,?,?,?)",
                               (rid, relation["from"], relation["to"], relation["type"], relation["label"],
                                relation.get("confidence", "explicit"), relation.get("perspective", "narrator"),
                                relation.get("status", "accepted"), relation.get("note", "")))
                db.execute(
                    """DELETE FROM RelationEvidence WHERE relation_id=? AND evidence_id IN
                       (SELECT id FROM Evidence WHERE work_id=?)""",
                    (rid, work["id"]),
                )
                for needle in relation["evidence"]:
                    db.execute("INSERT OR IGNORE INTO RelationEvidence VALUES (?,?)", (rid, evidence(needle)))

            narrator = db.execute("SELECT notes FROM Person WHERE id=?", (result["narrator"],)).fetchone()
            if narrator and result.get("narrator_note") and result["narrator_note"] not in (narrator[0] or ""):
                db.execute("UPDATE Person SET notes=trim(coalesce(notes,'') || ' ' || ?) WHERE id=?",
                           (result["narrator_note"], result["narrator"]))
            db.execute("INSERT INTO ContextReadingWork VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(work_id) DO UPDATE SET status=excluded.status,narrator_id=excluded.narrator_id,summary=excluded.summary,narrator_note=excluded.narrator_note,result_sha256=excluded.result_sha256,updated_at=CURRENT_TIMESTAMP",
                       (work["id"], result["status"], result["narrator"], result["summary"],
                        result.get("narrator_note", ""), digest(json.dumps(result, ensure_ascii=False, sort_keys=True))))
    export(db)
    print("Stateful readings applied:", len(results["works"]))
    db.close()


if __name__ == "__main__":
    main()
