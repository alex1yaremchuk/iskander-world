"""Add explicit relations missed during the first context-reading pass.

The source list is deliberately editorial.  Descriptions are used to locate
suspect omissions, but every materialized edge cites the original paragraph
behind one of the involved character cards.
"""
import json
import sqlite3

from bulk_extract import export
from inventory import ROOT, digest


# from, to, type, label, evidence owner, confidence
EDGES = [
    ("oldenburg_adjutant", "oldenburg", "serves", "Адъютант → принц", "oldenburg_adjutant", "explicit"),
    ("antsiferov_classmate", "chik", "classmate", "Одноклассники", "antsiferov_classmate", "explicit"),
    ("chik", "white_hen_chik", "owns", "Хозяин курицы", "white_hen_chik", "explicit"),
    ("kozlotur_editor_ex", "narrator", "editor", "Редактор рассказчика", "kozlotur_editor_ex", "explicit"),
    ("train_companion_gaze", "narrator", "companion", "Попутчики в вагоне", "train_companion_gaze", "explicit"),
    ("vasily_markovich_scorpion", "sergey_bashkapsarov", "acquaintance", "Курортный знакомый семьи", "vasily_markovich_scorpion", "explicit"),
    ("nazim_widow_australia", "nazim_hikmet", "spouse", "Вдова Назыма Хикмета", "nazim_widow_australia", "explicit"),
    ("school_waltz_vladimir_varlamovich", "chik", "family_friend", "Друг семьи; помогает Чику поступить в школу", "school_waltz_vladimir_varlamovich", "explicit"),
    ("stalin", "stalin_grandson_story", "grandparent", "Дед → внук", "stalin_grandson_story", "explicit"),
    ("dasha_garrison_officer", "alikhan_dasha", "former_partner", "Бывшие любовники", "dasha_garrison_officer", "explicit"),
    ("daur_amra", "bocho", "friend", "Товарищи по компании", "daur_amra", "explicit"),
    ("narrator", "man_named_war", "acquaintance", "Деревенские знакомые", "man_named_war", "explicit"),
    ("spring_poem_grandfather", "narrator", "grandparent", "Дед → внук-рассказчик", "spring_poem_grandfather", "inferred"),
    ("narrator", "dissident_forest_night_carriage", "acquaintance", "Знакомые; гуляют вместе", "dissident_forest_night_carriage", "explicit"),
    ("zoya_scorpion", "sergey_bashkapsarov", "acquaintance", "Знакомятся у пруда и идут на танцы", "zoya_scorpion", "explicit"),
    ("zurab_scorpion", "lara_bashkapsarova", "acquaintance", "Курортные знакомые", "zurab_scorpion", "explicit"),
    ("klavushka_ukraine", "viktor_maksimovich_kartashov", "acquaintance", "Принята семьёй Карташова", "klavushka_ukraine", "explicit"),
    ("school_waltz_liza", "school_waltz_erik", "sibling", "Сестра и брат", "school_waltz_liza", "explicit"),
    ("narrator", "camp_sleepwalker_night_carriage", "acquaintance", "Знакомые", "camp_sleepwalker_night_carriage", "explicit"),
    ("boris_borzov_geneticist", "manuel_rodriguez_poet", "acquaintance", "Борзов представляет поэта своим знакомым", "manuel_rodriguez_poet", "strongly_implied"),
    ("abkhaz_policeman_chik_street", "chik", "acquaintance", "Знаком семье Чика и помогает мальчику", "abkhaz_policeman_chik_street", "explicit"),
    ("uncle_tengiz_guard_adgur", "adgur", "protects", "Помогает заключённому Адгуру", "uncle_tengiz_guard_adgur", "explicit"),
    ("nadusha", "abesalomon", "works_for", "Секретарша Абесаломона Нартовича", "nadusha", "explicit"),
    ("rabbit_guard_chief", "rabbit_king", "serves", "Начальник королевской охраны", "rabbit_guard_chief", "explicit"),
    ("kodor_expert_fisherman", "narrator", "teacher", "Учит рассказчика ловить форель", "kodor_expert_fisherman", "explicit"),
    ("chik_chiromancer", "chik_chiromancer_donkey", "owns", "Хозяин ослика", "chik_chiromancer_donkey", "explicit"),
    ("anzor_coach_assistant", "anzor_dynamo_coach", "works_for", "Помощник тренера", "anzor_coach_assistant", "explicit"),
    ("lakoba_elderly_witness", "lakoba", "witness", "Свидетель и пересказчик речи Лакобы", "lakoba_elderly_witness", "explicit"),
    ("narrator", "debtors_driver_friend", "friend", "Приятели", "debtors_driver_friend", "explicit"),
    ("narrator", "pasternak_poetry_friend", "friend", "Студенческие приятели", "pasternak_poetry_friend", "explicit"),
    ("narrator", "psychiatrist_writer_clinic", "acquaintance", "Знакомый врач", "psychiatrist_writer_clinic", "explicit"),
    ("drunk_train_attendant_night_carriage", "train_attendant_night_carriage", "colleague", "Напарники-проводники", "drunk_train_attendant_night_carriage", "explicit"),
    ("kyzym", "rapka_dog", "owns", "Собака семьи Кязыма", "rapka_dog", "explicit"),
    ("kyzym", "ryzhaya_dog", "owns", "Собака семьи Кязыма", "ryzhaya_dog", "explicit"),
    ("tsiala_mourning_storyteller", "aunt_tsiala", "friend", "Старые знакомые с Первой Подгорной", "tsiala_mourning_storyteller", "explicit"),
    ("narrator", "tv_editor_islander", "acquaintance", "Редактор и писатель", "tv_editor_islander", "explicit"),
    ("slavik_family_maid", "slavik", "works_for", "Служит в семье Славика", "slavik_family_maid", "explicit"),
    ("atary_straw_widow", "chik_mother", "landlord", "Сдаёт матери Чика комнату", "atary_straw_widow", "explicit"),
    ("nkvd_neighbor_uninvited", "tamara_ivanovna_uninvited", "neighbor", "Соседи по коммунальной квартире", "nkvd_neighbor_uninvited", "explicit"),
    ("sofia_dmitrievna_neighbor", "chik", "neighbor", "Соседка Чика", "sofia_dmitrievna_neighbor", "explicit"),
    ("school_monitor_nebuchadnezzar", "chik", "classmate", "Одноклассники", "school_monitor_nebuchadnezzar", "explicit"),
    ("achandara_old_winemaker", "leonty_luarsabovich_teacher", "neighbor", "Соседи в Ачандаре", "achandara_old_winemaker", "explicit"),
    ("strange_boat_fisherman", "chik", "acquaintance", "Приглашает Чика в лодку", "strange_boat_fisherman", "explicit"),
    ("bocho_bamboo_companion", "bocho", "friend", "Товарищи по ночной вылазке", "bocho_bamboo_companion", "explicit"),
    ("narrator_hunting_companion_plot", "narrator", "companion", "Товарищи по охоте", "narrator_hunting_companion_plot", "explicit"),
    ("anzor_dynamo_coach", "anzor_guide", "teacher", "Тренер замечает и приглашает Анзора", "anzor_dynamo_coach", "explicit"),
    ("school_waltz_aunt_medea", "chik_aunt", "friend", "Подруги", "school_waltz_aunt_medea", "explicit"),
    ("rich_tailor_mother_in_law", "rich_tailor_wife", "parent", "Мать → дочь", "rich_tailor_mother_in_law", "explicit"),
    ("chik_history_teacher_greek", "chik", "teacher", "Учитель истории → ученик", "chik_history_teacher_greek", "explicit"),
    ("chik_history_teacher_greek", "sevastyanov_chik_classmate", "teacher", "Учитель истории → ученик", "chik_history_teacher_greek", "explicit"),
    ("larisa_chik", "wolfhound_puppy_larisa", "owns", "Хозяйка щенка", "wolfhound_puppy_larisa", "explicit"),
    ("edik_third_hill_midfielder", "anesti_boatswain", "rival", "Соперники на футбольном поле", "edik_third_hill_midfielder", "explicit"),
    ("remzik_yashka", "remzik", "cousin", "Двоюродные братья", "remzik_yashka", "explicit"),
    ("remzik_grandmother_sofichka", "remzik_yashka", "grandparent", "Бабушка → внук", "remzik_yashka", "explicit"),
    ("narrator", "fisher_story_schoolmate", "classmate", "Школьные товарищи", "fisher_story_schoolmate", "explicit"),
    ("shaadat_hunter", "viktor_maksimovich_kartashov", "companion", "Сопровождает Карташова в горах", "shaadat_hunter", "explicit"),
    ("old_gabunia", "chik", "acquaintance", "Рассказывает Чику старую историю", "old_gabunia", "strongly_implied"),
    ("local_teacher", "tali", "examines", "Проверяет рассказ о чуде младенца Тали", "local_teacher", "explicit"),
    ("journalist_evening_garden", "viktor_maksimovich_kartashov", "interviews", "Приезжает писать о Карташове", "journalist_evening_garden", "explicit"),
    ("zana_wild_woman", "viktor_maksimovich_kartashov", "research_subject", "Карташов исследует предание о Зане", "zana_wild_woman", "explicit"),
    ("georgy_semenov_writer", "narrator", "acquaintance", "Писатели-знакомые", "georgy_semenov_writer", "explicit"),
    ("geno_ioseliani", "narrator", "host", "Принимает рассказчика у себя", "geno_ioseliani", "explicit"),
    ("mullah", "father_sandro", "serves", "Приглашён Хабугом для обряда", "mullah", "explicit"),
    ("suliko_icecream_giant", "uncle_yura_driver", "acquaintance", "Городские знакомые и собеседники", "suliko_icecream_giant", "explicit"),
    ("slutsky_akinsman", "narrator", "relative", "Родственник рассказчика", "slutsky_akinsman", "strongly_implied"),
    ("school_waltz_adil", "chik", "acquaintance", "Знакомятся у поезда при высылке семей", "school_waltz_adil", "explicit"),
    ("alexander_men", "narrator", "acquaintance", "Рассказывает автору личную историю", "alexander_men", "explicit"),
    ("beradze_classmate_aphorisms", "chik", "classmate", "Одноклассники", "beradze_classmate_aphorisms", "explicit"),
    ("roof_football_fan_chik", "kostya_sleeping_football_fan", "neighbor", "Соседи у стадиона", "roof_football_fan_chik", "explicit"),
    ("remzik_vika", "remzik_city", "friend", "Знакомые; Вика слушает рассказы Ремзика", "remzik_vika", "explicit"),
    ("military_man_motya_scene", "motya_wooden", "conflict", "Пытается остановить расправу Моти", "military_man_motya_scene", "explicit"),
    ("palermo_delegation_general", "narrator", "companion", "Гуляют и беседуют в Палермо", "palermo_delegation_general", "explicit"),
    ("happy_findings_host_uncle", "chik", "relative", "Дядя Чика", "happy_findings_host_uncle", "explicit"),
    ("flickering_party_worker", "narrator", "acquaintance", "Знакомы с детства", "flickering_party_worker", "explicit"),
    ("flickering_party_worker", "mikhail_arkadievich_white", "conflict", "Идеологические спорщики", "flickering_party_worker", "explicit"),
    ("cow_fining_policeman", "chik", "conflict", "Штрафует и задерживает Чика", "cow_fining_policeman", "explicit"),
    ("police_chief_animals_city", "chik_uncle_kolya", "protects", "Проверяет историю и отпускает задержанных", "police_chief_animals_city", "explicit"),
    ("debtors_common_acquaintance", "narrator", "acquaintance", "Общий знакомый", "debtors_common_acquaintance", "explicit"),
    ("debtors_common_acquaintance", "vanechka_mamba", "acquaintance", "Общий знакомый", "debtors_common_acquaintance", "explicit"),
    ("siberian_classmate_aphorisms", "narrator", "classmate", "Одноклассники", "siberian_classmate_aphorisms", "explicit"),
    ("chik_old_librarian", "chik", "conflict", "Требует вернуть потерянную книгу", "chik_old_librarian", "explicit"),
    ("lost_chicken_woman", "chik", "neighbor", "Соседка просит найти курицу", "lost_chicken_woman", "explicit"),
    ("chanta_shepherd", "narrator", "host", "Принимает рассказчика на горной стоянке", "chanta_shepherd", "explicit"),
    ("chanta_shepherd", "andrei_tarkilov", "host", "Принимает Андрея на горной стоянке", "chanta_shepherd", "explicit"),
    ("serzh_beria_day", "narrator", "companion", "Случайные спутники в ночь ареста Берии", "serzh_beria_day", "explicit"),
]


def full_paragraph_evidence(db, edge, owner_id):
    owner = db.execute("SELECT evidence_json FROM Person WHERE id=?", (owner_id,)).fetchone()
    assert owner, owner_id
    evidence_ids = json.loads(owner[0] or "[]")
    assert evidence_ids, owner_id

    # Prefer a paragraph containing a recognizable token from the counterpart;
    # otherwise the owner's editorial anchor is still the reviewed paragraph
    # from which its relational description was written.
    counterpart = edge[1] if owner_id == edge[0] else edge[0]
    other = db.execute("SELECT canonical_name FROM Person WHERE id=?", (counterpart,)).fetchone()
    tokens = [] if not other else [
        token.casefold().replace("ё", "е")
        for token in other[0].replace("—", " ").replace("(", " ").replace(")", " ").split()
        if len(token) >= 4
    ]
    candidates = []
    for evidence_id in evidence_ids:
        row = db.execute(
            """SELECT e.*,t.text FROM Evidence e JOIN TextFragment t ON t.id=e.fragment_id
               WHERE e.id=?""",
            (evidence_id,),
        ).fetchone()
        if row:
            normalized = row["text"].casefold().replace("ё", "е")
            candidates.append((sum(token in normalized for token in tokens), row))
    assert candidates, owner_id
    source = max(candidates, key=lambda item: item[0])[1]
    evidence_id = "audit_ev_" + digest(":".join(edge[:3]) + ":" + source["id"])[:24]
    db.execute(
        "INSERT OR REPLACE INTO Evidence VALUES (?,?,?,?,?,?,?,?,?)",
        (evidence_id, source["work_id"], source["source_id"], source["fragment_id"],
         source["text"], 0, len(source["text"]), source["location"], "relation_audit"),
    )
    return evidence_id


def write_report(db, added):
    linked = {
        row[0] for row in db.execute(
            """SELECT from_person FROM Relation WHERE status IN ('accepted','reported')
               UNION SELECT to_person FROM Relation WHERE status IN ('accepted','reported')"""
        )
    }
    remaining = db.execute(
        "SELECT id,canonical_name,description,kind FROM Person WHERE id NOT LIKE 'bulk_%' ORDER BY canonical_name"
    ).fetchall()
    remaining = [row for row in remaining if row["id"] not in linked]
    lines = [
        "# Аудит пропущенных связей",
        "",
        f"Проверены описания всех персонажей; отдельно просмотрены все карточки без связей. "
        f"Добавлено явных связей: **{added}**. После прохода без связей осталось: **{len(remaining)}**.",
        "",
        "Оставшиеся карточки — преимущественно исторические и литературные упоминания, "
        "самостоятельные одноэпизодные фигуры, группы либо персонажи, для которых в базе "
        "нет отдельной карточки второго участника. Случайная встреча сама по себе связью не считается.",
        "",
        "## Добавленные связи",
        "",
    ]
    for a, b, relation_type, label, _, confidence in EDGES:
        left = db.execute("SELECT canonical_name FROM Person WHERE id=?", (a,)).fetchone()[0]
        right = db.execute("SELECT canonical_name FROM Person WHERE id=?", (b,)).fetchone()[0]
        lines.append(f"- **{left}** → **{right}** — {label} (`{relation_type}`, {confidence})")
    lines.extend(["", "## Проверенные карточки, оставшиеся без связей", ""])
    for row in remaining:
        lines.append(f"- **{row['canonical_name']}** (`{row['id']}`, {row['kind']}) — {row['description']}")
    lines.append("")
    (ROOT / "MISSING_RELATION_AUDIT.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main():
    db = sqlite3.connect(ROOT / "data" / "inventory.sqlite")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    with db:
        old_ids = [row[0] for row in db.execute("SELECT id FROM Relation WHERE id LIKE 'audit_rel_%'")]
        for relation_id in old_ids:
            db.execute("DELETE FROM RelationEvidence WHERE relation_id=?", (relation_id,))
        db.execute("DELETE FROM Relation WHERE id LIKE 'audit_rel_%'")
        db.execute("DELETE FROM Evidence WHERE id LIKE 'audit_ev_%'")

        added = 0
        for edge in EDGES:
            from_person, to_person, relation_type, label, owner_id, confidence = edge
            assert db.execute("SELECT 1 FROM Person WHERE id=?", (from_person,)).fetchone(), from_person
            assert db.execute("SELECT 1 FROM Person WHERE id=?", (to_person,)).fetchone(), to_person
            evidence_id = full_paragraph_evidence(db, edge, owner_id)
            existing = db.execute(
                """SELECT id FROM Relation WHERE from_person=? AND to_person=? AND type=?
                   AND status!='rejected' LIMIT 1""",
                (from_person, to_person, relation_type),
            ).fetchone()
            if existing:
                relation_id = existing[0]
            else:
                relation_id = "audit_rel_" + digest(":".join(edge[:3]))[:24]
                db.execute(
                    "INSERT INTO Relation VALUES (?,?,?,?,?,?,?,?,?)",
                    (relation_id, from_person, to_person, relation_type, label, confidence,
                     "narrator", "accepted", "Добавлено при аудите описаний персонажей без связей."),
                )
                added += 1
            db.execute("INSERT OR IGNORE INTO RelationEvidence VALUES (?,?)", (relation_id, evidence_id))

        write_report(db, added)

    export(db)
    assert not db.execute("PRAGMA foreign_key_check").fetchall()
    db.close()
    print(f"Relation audit applied: {added} new relations from {len(EDGES)} reviewed omissions")


if __name__ == "__main__":
    main()
