"""Linear, resumable close-reading pass over the canonical prose corpus.

The pass deliberately separates reading from entity resolution.  Every work is
opened once.  Known-person mentions can safely extend Appearance; relationship
sentences and unknown names go to a durable review queue instead of creating a
quadratic cloud of person pairs.
"""
import json
import re
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from inventory import ROOT, digest, local, text
from pilot_seed import PEOPLE

RUN_ID = "deep_read_v1"
PROSE = {"cycle_story", "essay", "novel_chapter", "work", "work_part", "notes"}
REL_WORDS = re.compile(
    r"(?i)\b(?:отец|мать|мама|папа|сын|дочь|брат|сестра|дядя|т[её]тя|"
    r"дед|бабушк\w*|внук\w*|племянник\w*|жен\w*|муж\w*|невест\w*|жених\w*|"
    r"родственник\w*|друг\w*|приятел\w*|враг\w*|соперник\w*|любил\w*|"
    r"ненавидел\w*|убил\w*|спас\w*|помог\w*)\b"
)
NAME = re.compile(r"(?<![\w-])([А-ЯЁ][а-яё]{2,}(?:\s+[А-ЯЁ][а-яё]{2,}){0,2})(?![\w-])")
STOP = {"Это", "Вот", "Нет", "Да", "Как", "Но", "Что", "Когда", "Если", "Или",
        "После", "Перед", "Тогда", "Однако", "Он", "Она", "Они", "Мы", "Вы", "Я",
        "Россия", "Абхазия", "Москва", "Чегем", "Мухус"}


def paragraphs(work):
    out = []
    with zipfile.ZipFile(ROOT / "corpus" / work["source"]) as book:
        for resource in work["resources"]:
            body = ET.fromstring(book.read(resource)).find(".//{*}body")
            if body is None:
                continue
            for element in body.iter():
                if local(element) == "p":
                    value = text(element)
                    if value:
                        out.append((resource, value))
    return out


def compile_people():
    result = []
    for p in PEOPLE:
        if p.get("pattern"):
            result.append((p["id"], p["name"], re.compile(r"(?<!\w)(?:" + p["pattern"] + r")(?!\w)")))
    return result


def main():
    registry = json.loads((ROOT / "data" / "canonical_works.json").read_text(encoding="utf-8"))
    works = [w for w in registry if w.get("kind") in PROSE and w.get("source") and w.get("resources")]
    patterns = compile_people()
    db = sqlite3.connect(ROOT / "data" / "inventory.sqlite")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS DeepReadWork(
      work_id TEXT PRIMARY KEY REFERENCES Work(id), run_id TEXT, text_sha256 TEXT,
      paragraph_count INTEGER, known_mentions INTEGER, relation_windows INTEGER,
      status TEXT, processed_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS DeepReadItem(
      id TEXT PRIMARY KEY, run_id TEXT, work_id TEXT REFERENCES Work(id), item_type TEXT,
      paragraph_ordinal INTEGER, text TEXT, candidates_json TEXT, status TEXT,
      priority INTEGER, note TEXT);
    """)
    with db:
        db.execute("DELETE FROM DeepReadItem WHERE run_id=?", (RUN_ID,))
        db.execute("DELETE FROM MentionResolution WHERE mention_id IN (SELECT id FROM Mention WHERE run_id=?)", (RUN_ID,))
        db.execute("DELETE FROM Mention WHERE run_id=?", (RUN_ID,))
        db.execute("DELETE FROM ExtractionRun WHERE id=?", (RUN_ID,))
        db.execute("INSERT INTO ExtractionRun VALUES (?,?,?)", (RUN_ID, "linear_close_read",
                   json.dumps({"scope": "canonical prose", "version": 1}, ensure_ascii=False)))

        totals = Counter()
        for wi, work in enumerate(works, 1):
            pars = paragraphs(work)
            whole_hash = digest("\n".join(p[1] for p in pars))
            known_by_person = defaultdict(list)
            relation_count = 0
            unknown_counts = Counter()
            unknown_examples = {}
            for ordinal, (resource, para) in enumerate(pars, 1):
                hits = []
                for pid, pname, pattern in patterns:
                    for m in pattern.finditer(para):
                        hits.append((m.start(), m.end(), m.group(), pid, pname))
                        known_by_person[pid].append((ordinal, resource, para, m.start(), m.end(), m.group()))
                # Relationship-bearing paragraphs are the compact close-reading queue.
                if REL_WORDS.search(para):
                    relation_count += 1
                    candidates = sorted({h[3] for h in hits})
                    iid = "deep_rel_" + digest(work["id"] + ":" + str(ordinal))[:24]
                    db.execute("INSERT INTO DeepReadItem VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (iid, RUN_ID, work["id"], "relationship_context", ordinal, para,
                                json.dumps(candidates, ensure_ascii=False), "pending", 100 if len(candidates) >= 2 else 60,
                                "Абзац содержит явный маркер отношения; направление и сущности требуют проверки."))
                for m in NAME.finditer(para):
                    surface = m.group(1)
                    if surface not in STOP and surface.split()[0] not in STOP:
                        key = surface.replace("ё", "е").casefold()
                        unknown_counts[key] += 1
                        unknown_examples.setdefault(key, (surface, ordinal, para))

            # Known entities: one evidence/mention/appearance per work, no pairwise comparisons.
            for pid, hits in known_by_person.items():
                ordinal, resource, para, start, end, surface = hits[0]
                fid = "deep_para_" + digest(work["id"] + ":" + str(ordinal))[:24]
                db.execute("INSERT OR IGNORE INTO TextFragment VALUES (?,?,?,?,?,?,?)",
                           (fid, work["source_id"], 3000000 + ordinal, resource + "::p" + str(ordinal),
                            para, digest(para), json.dumps({"kind": "deep_read_paragraph"}, ensure_ascii=False)))
                db.execute("INSERT OR IGNORE INTO WorkFragment VALUES (?,?)", (work["id"], fid))
                eid = "deep_ev_" + digest(pid + ":" + work["id"])[:24]
                db.execute("INSERT INTO Evidence VALUES (?,?,?,?,?,?,?,?,?) "
                           "ON CONFLICT(id) DO UPDATE SET quote=excluded.quote,start_char=excluded.start_char,"
                           "end_char=excluded.end_char,location=excluded.location",
                           (eid, work["id"], work["source_id"], fid, surface, start, end,
                            resource + "::p" + str(ordinal), ""))
                mid = "deep_men_" + digest(pid + ":" + work["id"])[:24]
                db.execute("INSERT OR IGNORE INTO Mention VALUES (?,?,?,?,?,?,?,?,?)",
                           (mid, work["id"], fid, start, end, surface, json.dumps([pid]),
                            "known_person_pattern", RUN_ID))
                db.execute("INSERT OR IGNORE INTO MentionResolution VALUES (?,?,?,?,?)",
                           (mid, pid, "strongly_implied", eid,
                            "Словарный вариант имени найден при линейном чтении произведения."))
                db.execute("INSERT OR IGNORE INTO Appearance VALUES (?,?,?,?,?,?,?)",
                           ("deep_app_" + digest(pid + ":" + work["id"])[:24], pid, work["id"],
                            "mention", "strongly_implied", json.dumps([eid]),
                            "Повторное появление найдено по проверенному варианту имени."))

            # Repeated name-like strings become review items, not premature people.
            for key, count in unknown_counts.items():
                if count < 2:
                    continue
                surface, ordinal, para = unknown_examples[key]
                iid = "deep_name_" + digest(work["id"] + ":" + key)[:24]
                db.execute("INSERT INTO DeepReadItem VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (iid, RUN_ID, work["id"], "name_candidate", ordinal, para,
                            json.dumps([surface], ensure_ascii=False), "pending", min(90, 30 + count * 5),
                            f"Именная форма повторяется в произведении {count} раз."))

            db.execute("INSERT INTO DeepReadWork VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP) "
                       "ON CONFLICT(work_id) DO UPDATE SET run_id=excluded.run_id,text_sha256=excluded.text_sha256,"
                       "paragraph_count=excluded.paragraph_count,known_mentions=excluded.known_mentions,"
                       "relation_windows=excluded.relation_windows,status=excluded.status,processed_at=CURRENT_TIMESTAMP",
                       (work["id"], RUN_ID, whole_hash, len(pars), sum(map(len, known_by_person.values())),
                        relation_count, "read"))
            totals.update(works=1, paragraphs=len(pars), known_mentions=sum(map(len, known_by_person.values())),
                          known_person_work_pairs=len(known_by_person), relation_windows=relation_count,
                          name_candidates=sum(1 for n in unknown_counts.values() if n >= 2))
            if wi % 25 == 0:
                print(f"read {wi}/{len(works)} works")

    report = {"run_id": RUN_ID, "works_in_scope": len(works), **totals}
    (ROOT / "DEEP_READ_REPORT.md").write_text(
        "# Линейное подробное чтение корпуса\n\n"
        + "Первый проход завершён по всему прозаическому реестру. Произведение читается один раз; "
          "межтекстовое объединение вынесено из прохода.\n\n"
        + "\n".join(f"- {k}: {v}" for k, v in report.items()) + "\n",
        encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
