"""Reconcile duplicate character cards after all reading layers are applied.

The fast whole-corpus pass intentionally creates disposable ``bulk_*`` people.
Once a name has exactly one editorial counterpart, spelling-only differences
(including е/ё) must not leave two cards on the site.
"""
import json
import re
import sqlite3
from collections import defaultdict

from bulk_extract import export
from inventory import ROOT, digest
from apply_stateful_reading import PERSON_ID_ALIASES


# Duplicates confirmed by reading rather than by spelling alone.
CONFIRMED_MERGES = {
    old_id: new_id for old_id, new_id in PERSON_ID_ALIASES.items()
    if not old_id.startswith("bulk_") and old_id not in {"narrator_mother", "kama_big_house"}
}

# The capitalized-name pass also mistakes Russian case forms for new people.
# These pairs were checked against their source appearances; unlike fuzzy
# matching at runtime, the explicit list cannot collapse a merely similar name.
CONFIRMED_MERGES.update({
    "bulk_d50ac87c7719add05572269e": "avtandil_tsikridze",
    "bulk_525796660f2dfb9af82ff798": "alexandra_ivanovna",
    "bulk_a7827585ef01ccc12819c53c": "alexandra_ivanovna",
    "bulk_30b6541aedf453e89ed534ea": "alexandra_ivanovna",
    "bulk_f858671936680e4b7c08f603": "vanechka_mamba",
    "bulk_dfc0885b4ca8031d5c26827d": "alexander_men",
    "bulk_635898192cc31a7831609fa3": "nikolay_gumilyov",
    "bulk_d6c8c270b416c3fee7338592": "akakiy_makedonovich",
    "bulk_00d089f1b76680977b7267da": "akakiy_makedonovich",
    "bulk_65d496f9e9b983226c4d28d2": "yura_stavrakidi",
    "bulk_4675910f978efb0bec0806d1": "vasily_markovich_scorpion",
    "bulk_99e1985c9a447f193aeef354": "evgenia_alexandrovna_neighbor",
    "bulk_f67a83e0b9838484e9f99d48": "evgenia_alexandrovna_neighbor",
    "bulk_93ce66d82d204941113f55c0": "sofia_dmitrievna_neighbor",
    "bulk_0799504efba896cfac27f250": "platon",
    "bulk_bee5fa5999e3606ad847580c": "pata",
    "bulk_02aa5a335c29f764ca03bed5": "pata",
    "bulk_5f97b94593e52db3ae19309e": "pata",
    "bulk_bbf9d506a12be7cafc6564dc": "koli_zarkhidi",
    "bulk_488d211f2dd935e882a43d56": "koli_zarkhidi",
    "bulk_bc7c5b4eaf56219f3718ec2b": "timur_zhvanba",
    "bulk_f59af44535ddfc2904a634d9": "lakoba",
    "bulk_257df406473dbd58bed031df": "lakoba",
    "bulk_d75876aee084ff286f0e0120": "masha",
    "bulk_c625161b1b8c5c1ae57a22b9": "beria",
    "bulk_425794990b8d68a47c6d0b35": "god_poetic",
    "bulk_d75ea10ced3141c0b86eaf1d": "hadjarat_kyakhba",
    "bulk_04ce40409f104d91d784d65d": "hadjarat_kyakhba",
    "bulk_4fdd06b58f3773817087b9a4": "georgy_georgievich_poet",
    "bulk_9ad76a1503e1363183de6b95": "georgy_georgievich_poet",
    "bulk_7919f7028c2addba1607bb56": "inessa",
    "bulk_fbc4cd58583834fed1b51945": "inessa",
    "bulk_65790ae6a33733d3cafa8ae2": "alexey_ivanovich_camp",
    "bulk_cfb6cfb5ad3bc7ea7afda0a1": "alexey_ivanovich_camp",
    "bulk_fa88bfbc983ddadfc382f6d8": "alexey_ivanovich_camp",
    "bulk_98fb4cfe49aad27e8aa13f6e": "alexander_aristarkhovich",
    "bulk_37917dc7d8855ddd7e1dd68a": "alexander_aristarkhovich",
    "bulk_d9139e9c4822c8cdf27170ca": "andrei_tarkilov",
    "bulk_0ad55f632eb6ce7bd7c8db05": "abesalomon",
    "bulk_f939cc2438faaa7c6e4e72f7": "abesalomon",
    "bulk_bd71768846421bea8a8ad830": "alfred_ivanovich_physicist",
    "bulk_a478162aa4f4873df4753598": "alfred_ivanovich_physicist",
    "bulk_53119651c5ced8fd7a602ce8": "alexey_efremovich_general",
    "bulk_2044cd2506abf0946fde2416": "alexey_efremovich_general",
    "bulk_ac6e0e3cd39ffb4b50a2160b": "leonty_luarsabovich_teacher",
    "bulk_6c13fbe4adf3f834118f266e": "mikhail_bulgakov",
    "bulk_6cc6d5af456cc5f66cda00e6": "tamara_ivanovna_uninvited",
    "bulk_c7ccb808a9ee097679130a01": "nazim_hikmet",
    "bulk_5536fd4e9ccaf6e8002f9d16": "nazim_hikmet",
})


def normalized_name(value):
    value = value.casefold().replace("ё", "е")
    value = value.replace("—", "-").replace("–", "-")
    value = re.sub(r"[«»„“”\"'()]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def merge_person(db, old_id, new_id):
    if old_id == new_id:
        return False
    old = db.execute("SELECT * FROM Person WHERE id=?", (old_id,)).fetchone()
    new = db.execute("SELECT * FROM Person WHERE id=?", (new_id,)).fetchone()
    if not old:
        return False
    assert new, (old_id, new_id)

    evidence = list(dict.fromkeys(json.loads(new["evidence_json"]) + json.loads(old["evidence_json"])))
    notes = " ".join(dict.fromkeys(x for x in (new["notes"] or "", old["notes"] or "") if x))
    # Prefer the fuller editorial description, never the automatic placeholder.
    descriptions = [x for x in (new["description"] or "", old["description"] or "")
                    if "Автоматически выделенное имя" not in x]
    description = max(descriptions, key=len, default=new["description"] or old["description"])
    kind = new["kind"] if new["kind"] != "candidate" else old["kind"]
    db.execute(
        "UPDATE Person SET description=?,kind=?,notes=?,evidence_json=? WHERE id=?",
        (description, kind, notes, json.dumps(evidence), new_id),
    )

    # Keep the discarded spelling searchable.
    if normalized_name(old["canonical_name"]) != normalized_name(new["canonical_name"]):
        alias_id = "alias_merge_" + digest(new_id + ":" + old["canonical_name"])[:20]
        db.execute(
            "INSERT OR IGNORE INTO Alias VALUES (?,?,?,?,?)",
            (alias_id, new_id, old["canonical_name"], None, json.loads(old["evidence_json"])[0]),
        )

    for old_app in db.execute("SELECT * FROM Appearance WHERE person_id=?", (old_id,)).fetchall():
        new_app = db.execute(
            "SELECT * FROM Appearance WHERE person_id=? AND work_id=?", (new_id, old_app["work_id"])
        ).fetchone()
        if new_app:
            combined = list(dict.fromkeys(
                json.loads(new_app["evidence_json"]) + json.loads(old_app["evidence_json"])
            ))
            roles = {"mention": 0, "episode": 1, "secondary": 2, "main": 3}
            role = max((new_app["role"], old_app["role"]), key=lambda x: roles.get(x, 0))
            confidence = new_app["confidence"] if new_app["confidence"] != "uncertain" else old_app["confidence"]
            db.execute(
                "UPDATE Appearance SET role=?,confidence=?,evidence_json=? WHERE id=?",
                (role, confidence, json.dumps(combined), new_app["id"]),
            )
            db.execute("DELETE FROM Appearance WHERE id=?", (old_app["id"],))
        else:
            db.execute("UPDATE Appearance SET person_id=? WHERE id=?", (new_id, old_app["id"]))

    for table, column in (
        ("Alias", "person_id"),
        ("MentionResolution", "person_id"),
        ("PersonPlace", "person_id"),
        ("CorpusHit", "person_id"),
        ("ReviewItem", "candidate_person_id"),
    ):
        db.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (new_id, old_id))
    db.execute("UPDATE Relation SET from_person=? WHERE from_person=?", (new_id, old_id))
    db.execute("UPDATE Relation SET to_person=? WHERE to_person=?", (new_id, old_id))
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ContextReadingWork'").fetchone():
        db.execute("UPDATE ContextReadingWork SET narrator_id=? WHERE narrator_id=?", (new_id, old_id))
    db.execute("DELETE FROM Person WHERE id=?", (old_id,))
    return True


def tidy_relations(db):
    self_edges = [x[0] for x in db.execute("SELECT id FROM Relation WHERE from_person=to_person")]
    for relation_id in self_edges:
        db.execute("DELETE FROM RelationEvidence WHERE relation_id=?", (relation_id,))
        db.execute("DELETE FROM Relation WHERE id=?", (relation_id,))

    groups = db.execute(
        """SELECT from_person,to_person,type,status,group_concat(id) ids
           FROM Relation GROUP BY from_person,to_person,type,status HAVING count(*)>1"""
    ).fetchall()
    for group in groups:
        keep, *duplicates = group["ids"].split(",")
        for duplicate in duplicates:
            db.execute(
                "INSERT OR IGNORE INTO RelationEvidence SELECT ?,evidence_id FROM RelationEvidence WHERE relation_id=?",
                (keep, duplicate),
            )
            db.execute("DELETE FROM RelationEvidence WHERE relation_id=?", (duplicate,))
            db.execute("DELETE FROM Relation WHERE id=?", (duplicate,))


def main():
    db = sqlite3.connect(ROOT / "data" / "inventory.sqlite")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    merged = []
    with db:
        for old_id, new_id in CONFIRMED_MERGES.items():
            if merge_person(db, old_id, new_id):
                merged.append((old_id, new_id, "confirmed"))

        # A bulk card may be folded only when the normalized name has exactly
        # one editorial identity. Homonyms such as the two Omars stay separate.
        groups = defaultdict(list)
        for person in db.execute("SELECT id,canonical_name FROM Person"):
            groups[normalized_name(person["canonical_name"])].append(person["id"])
        for ids in groups.values():
            bulk_ids = [x for x in ids if x.startswith("bulk_")]
            editorial_ids = [x for x in ids if not x.startswith("bulk_")]
            if len(editorial_ids) != 1:
                continue
            for old_id in bulk_ids:
                if merge_person(db, old_id, editorial_ids[0]):
                    merged.append((old_id, editorial_ids[0], "normalized-name"))
        tidy_relations(db)

    export(db)
    assert not db.execute("PRAGMA foreign_key_check").fetchall()
    db.close()
    print(f"Reconciled people: {len(merged)}")
    for old_id, new_id, reason in merged:
        print(f"  {old_id} -> {new_id} ({reason})")


if __name__ == "__main__":
    main()
