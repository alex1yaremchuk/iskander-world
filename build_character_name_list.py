"""Build a human review list of character names, ordered by graph importance."""
import json
import re
from collections import defaultdict

from inventory import ROOT


PREFIXES = re.compile(
    r"^(?:т[её]т(?:я|ушка)|дядя|дядюшка|старик|старый|молодой|князь|княгиня|"
    r"принц|принцесса|дедушка|бабушка|товарищ|доктор|генерал|царь|"
    r"профессор|полковник|капитан|майор|адвокат|поэт|писатель|мясник|пастух|"
    r"инженер|мороженщик|товаровед)\s+",
    re.IGNORECASE,
)
ROLE_PREFIXES = re.compile(
    r"^(?:жена|муж|мать|отец|сын|дочь|брат|сестра|родители|семья|хозяин|"
    r"хозяйка|рассказчик|приятель|друг|подруга|учитель|учительница|сосед|соседка)\b",
    re.IGNORECASE,
)
LOWERCASE_PARTICLES = {"де", "дель", "фон", "ван", "ибн", "аль"}
NON_NAME_WORDS = re.compile(
    r"\b(?:брата?|братья|сестры?|сестра|матери|мать|отца|отец|сына?|сыновья|дочери|дочь|"
    r"мужа?|жены?|жена|внука?|внучка|дед|бабка|бабушка|родственники|семья|"
    r"учитель|учительница|сосед|соседка|товарищ|приятель|подруга|хозяин|хозяйка|"
    r"рассказчик|мальчик|мальчики|девочка|женщина|мужчина|старик|старуха|вдова|вдовушка|"
    r"мачеха|зять|племянник|родственник|друзья|воспитанник|врач)\b",
    re.IGNORECASE,
)
GENERIC_LABELS = {
    "жених", "задумавшийся", "мухусчанин", "карманщик", "автоинспектор", "актриса",
    "завмаг", "находчивый", "проводница", "художник", "краснорубашечник", "армавирец",
    "велосипедист", "делец", "джазист", "доктор", "князь", "майор", "народоволец",
    "полковник", "режиссёр", "силач", "филолог", "фининспектор", "мальчики", "писатель",
    "почтальонша", "уголовник", "пастухи башкапсара", "тёща богатого портного",
}


def base_name(value):
    value = re.sub(r"\s*\([^)]*\)\s*$", "", value).strip()
    value = re.split(r"\s+[—–]\s+", value, maxsplit=1)[0].strip()
    previous = None
    while previous != value:
        previous = value
        value = PREFIXES.sub("", value).strip()
    return value


def is_proper_name(original, value):
    """Keep names/nicknames, not anonymous editorial descriptions."""
    if not value or ROLE_PREFIXES.match(value) or NON_NAME_WORDS.search(value):
        return False
    if value.casefold().replace("ё", "е") == "чика":
        return False
    if value.casefold() in GENERIC_LABELS:
        return False
    if any(mark in value for mark in (",", "«", "»", '"', "/")):
        return False
    words = value.split()
    if len(words) > 4:
        return False
    for word in words:
        parts = word.split("-")
        for part in parts:
            clean = part.strip(".()")
            if not clean or clean.casefold() in LOWERCASE_PARTICLES:
                continue
            if not clean[0].isupper():
                return False
    return bool(re.search(r"[А-ЯЁ]", value))


def main():
    data = json.loads((ROOT / "data" / "pilot_export.json").read_text(encoding="utf-8"))
    appearances = defaultdict(set)
    neighbours = defaultdict(set)
    for item in data["appearances"]:
        appearances[item["person_id"]].add(item["work_id"])
    for item in data["relations"]:
        neighbours[item["from_person"]].add(item["to_person"])
        neighbours[item["to_person"]].add(item["from_person"])

    grouped = {}
    for person in data["people"]:
        if person["id"].startswith("bulk_"):
            continue
        name = base_name(person["canonical_name"])
        if not is_proper_name(person["canonical_name"], name):
            continue
        key = name.casefold().replace("ё", "е")
        score = 20 * len(neighbours[person["id"]]) + 10 * len(appearances[person["id"]]) + min(person["mention_count"], 100)
        record = grouped.setdefault(
            key, {"name": name, "score": 0, "works": set(), "links": set(), "people": set()}
        )
        if score > record["score"]:
            record["name"] = name
        record["score"] = max(record["score"], score)
        record["works"].update(appearances[person["id"]])
        record["links"].update(neighbours[person["id"]])
        record["people"].add(person["id"])

    names = sorted(grouped.values(), key=lambda x: (-x["score"], x["name"].casefold()))
    lines = [
        "# Имена персонажей для ручной проверки", "",
        "Список построен из редакционных карточек. Обращения вроде «дядя», «тётя», «князь» и «старик» сняты. "
        "Порядок определяется числом связей, произведений и подтверждённых упоминаний.", "",
    ]
    for index, item in enumerate(names, 1):
        duplicate_note = f"; карточек с этим базовым именем: {len(item['people'])}" if len(item["people"]) > 1 else ""
        lines.append(
            f"{index}. **{item['name']}** — произведений: {len(item['works'])}; "
            f"связей: {len(item['links'])}{duplicate_note}"
        )
    (ROOT / "CHARACTER_NAMES.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"Character names for review: {len(names)}")


if __name__ == "__main__":
    main()
