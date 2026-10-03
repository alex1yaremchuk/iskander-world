"""Apply reviewed facts found by sequential, stateful reading."""
import json
import sqlite3

from bulk_extract import export
from deep_read import paragraphs
from inventory import ROOT, digest


READINGS = [
    {
        "person": "chik_father",
        "title": "Школьный вальс, или энергия стыда",
        "needle": "Отец, конечно, попал в число самых первых",
        "role": "secondary",
    },
    {
        "person": "chik_father",
        "title": "Красота нормы, или мальчик ждет человека",
        "needle": "За предвоенные годы на их семью обрушилось столько горя",
        "role": "mention",
    },
]


def main():
    registry = json.loads((ROOT / "data" / "canonical_works.json").read_text(encoding="utf-8"))
    db = sqlite3.connect(ROOT / "data" / "inventory.sqlite")
    db.row_factory = sqlite3.Row
    evidence_ids = []
    with db:
        for record in READINGS:
            work = next(w for w in registry if w.get("source") and w["title"] == record["title"])
            found = [(i, resource, value) for i, (resource, value) in enumerate(paragraphs(work), 1)
                     if record["needle"] in value]
            assert len(found) == 1, (record["title"], len(found))
            ordinal, resource, value = found[0]
            fid = "context_para_" + digest(work["id"] + ":" + str(ordinal))[:24]
            location = resource + "::p" + str(ordinal)
            db.execute("INSERT INTO TextFragment VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET text=excluded.text",
                       (fid, work["source_id"], 4000000 + ordinal, location, value, digest(value),
                        json.dumps({"kind": "reviewed_context"}, ensure_ascii=False)))
            db.execute("INSERT OR IGNORE INTO WorkFragment VALUES (?,?)", (work["id"], fid))
            start = value.index(record["needle"])
            eid = "context_ev_" + digest(record["person"] + ":" + work["id"])[:24]
            db.execute("INSERT INTO Evidence VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET quote=excluded.quote,start_char=excluded.start_char,end_char=excluded.end_char",
                       (eid, work["id"], work["source_id"], fid, record["needle"], start,
                        start + len(record["needle"]), location, ""))
            evidence_ids.append(eid)
            db.execute("INSERT OR IGNORE INTO Appearance VALUES (?,?,?,?,?,?,?)",
                       ("context_app_" + digest(record["person"] + ":" + work["id"])[:24],
                        record["person"], work["id"], record["role"], "explicit", json.dumps([eid]),
                        "Появление подтверждено последовательным чтением сюжетного контекста."))

        person = db.execute("SELECT evidence_json FROM Person WHERE id='chik_father'").fetchone()
        combined = list(dict.fromkeys(json.loads(person[0]) + evidence_ids))
        db.execute("UPDATE Person SET description=?,notes=?,evidence_json=? WHERE id='chik_father'", (
            "Отец Чика. Перед войной выслан по происхождению в Иран; пережил заключение и каторжные работы, "
            "но домой не вернулся. Семья позднее узнала, что он умер в 1957 году.",
            "Судьба рассказана от первого лица в «Школьном вальсе» и повторена в «Красоте нормы»; "
            "окружение мальчика совпадает с циклом о Чике.", json.dumps(combined)))

        eid = evidence_ids[0]
        db.execute("INSERT OR IGNORE INTO Place VALUES (?,?,?,?,?,?,?)",
                   ("iran", "Иран", "Страна", "Место высылки отца Чика.", 92, 86, json.dumps(evidence_ids)))
        db.execute("INSERT OR REPLACE INTO PersonPlace VALUES (?,?,?,?,?,?)",
                   ("pp_chik_father_iran", "chik_father", "iran", "Выслан; умер на чужбине", "explicit", eid))
    export(db)
    db.close()
    print("Applied reviewed context: Chik's father, exile to Iran, death in 1957")


if __name__ == "__main__":
    main()
