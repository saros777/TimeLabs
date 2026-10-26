from __future__ import annotations

from copy import deepcopy
from datetime import date
from uuid import uuid4


class RuleError(ValueError):
    pass


def uid() -> str:
    return uuid4().hex


def empty_project() -> dict:
    return {"schema": 1, "school": "Новая школа", "year": "2026–2027",
            "demo": False, "periods": 9, "weekdays": [1, 2, 3, 4, 5],
            "teachers": {}, "groups": {}, "rooms": {}, "subjects": {},
            "lessons": [], "days": {}, "absences": [], "obligations": [], "outbox": [],
            "rules": {"daily_limits": {}, "weekly_limits": {}, "approved": False}}


def members(project: dict, group_ids: list[str]) -> set[str]:
    result = set()
    for gid in group_ids:
        if gid not in project["groups"]:
            raise RuleError(f"Неизвестная группа: {gid}")
        result.update(project["groups"][gid]["members"])
    return result


def absent(project: dict, teacher: str, day: str, slot: int) -> bool:
    return any(a["teacher"] == teacher and a["start"] <= day <= a["end"]
               and (not a["slots"] or slot in a["slots"]) for a in project["absences"])


def day_lessons(project: dict, day: str) -> list[dict]:
    if day in project["days"]:
        return deepcopy(project["days"][day]["lessons"])
    weekday = date.fromisoformat(day).isoweekday()
    return deepcopy([x for x in project["lessons"] if x["weekday"] == weekday])


def validate(project: dict, lessons: list[dict], day: str | None = None) -> list[str]:
    errors, busy, loads, seen = [], {}, {}, set()
    for lesson in lessons:
        name = lesson.get("id", "?")
        if name in seen:
            errors.append(f"Дублируется ID занятия: {name}")
        seen.add(name)
        try:
            pupils = members(project, lesson["groups"])
            subject = project["subjects"][lesson["subject"]]
            room = project["rooms"][lesson["room"]]
            teachers = [project["teachers"][t] for t in lesson["teachers"]]
            if not pupils or not teachers or len(set(lesson["teachers"])) != len(teachers):
                raise RuleError("Пустой состав или повтор преподавателя")
            if lesson.get("status") == "cancelled":
                continue
            slot, duration = lesson["slot"], lesson.get("duration", 1)
            if not isinstance(slot, int) or not isinstance(duration, int) or duration < 1:
                raise RuleError("Некорректные номер урока или длительность")
            if slot < 1 or slot + duration - 1 > project["periods"]:
                raise RuleError("Урок вне сетки звонков")
            weekday = date.fromisoformat(day).isoweekday() if day else lesson["weekday"]
            if weekday not in project["weekdays"]:
                raise RuleError("Нерабочий учебный день")
            if len(pupils) > room["capacity"]:
                raise RuleError("Недостаточная вместимость кабинета")
            if not set(subject.get("equipment", [])) <= set(room.get("equipment", [])):
                raise RuleError("Нет обязательного оборудования кабинета")
            for t in teachers:
                if lesson["subject"] not in t["subjects"]:
                    raise RuleError(f"Нет допуска к предмету: {t['name']}")
            for period in range(slot, slot + duration):
                for tid in lesson["teachers"]:
                    if day and absent(project, tid, day, period):
                        raise RuleError(f"Отсутствует преподаватель: {project['teachers'][tid]['name']}")
                for kind, ids in (("teachers", lesson["teachers"]), ("rooms", [lesson["room"]])):
                    for rid in ids:
                        if [weekday, period] in project[kind][rid].get("unavailable", []):
                            raise RuleError(f"Ресурс недоступен: {project[kind][rid]['name']}")
                resources = [("учитель", t) for t in lesson["teachers"]]
                resources += [("кабинет", lesson["room"])] + [("ученик", s) for s in pupils]
                for kind, rid in resources:
                    key = (weekday, period, kind, rid)
                    if key in busy:
                        errors.append(f"Урок {period}: пересечение ({kind}) занятий {busy[key]} и {name}")
                    busy[key] = name
                for pupil in pupils:
                    loads[(weekday, pupil)] = loads.get((weekday, pupil), 0) + 1
        except (KeyError, TypeError, RuleError, ValueError) as exc:
            errors.append(f"Занятие {name}: {exc}")
    for gid, group in project["groups"].items():
        limit = project["rules"]["daily_limits"].get(gid)
        weekly = project["rules"].get("weekly_limits", {}).get(gid)
        for pupil in group["members"]:
            daily = [n for (w, p), n in loads.items() if p == pupil]
            if limit and any(n > limit for n in daily):
                errors.append(f"Превышен дневной лимит группы {group['name']}")
                break
            if not day and weekly and sum(daily) > weekly:
                errors.append(f"Превышен недельный лимит группы {group['name']}")
                break
    return sorted(set(errors))


def validate_project(project: dict) -> None:
    if project.get("schema") != 1:
        raise RuleError("Неподдерживаемая схема проекта")
    for key in empty_project():
        if key not in project:
            raise RuleError(f"Нет поля проекта: {key}")
    if not isinstance(project['school'], str) or not project['school'].strip():
        raise RuleError('Укажите название школы')
    if not project['weekdays'] or any(d not in range(1, 8) for d in project['weekdays']):
        raise RuleError('Некорректная учебная неделя')
    for kind in ('teachers', 'groups', 'rooms', 'subjects'):
        for key, record in project[kind].items():
            if not key or not record.get('name'):
                raise RuleError('Код и название ресурса обязательны')
    for teacher in project['teachers'].values():
        if not set(teacher['subjects']) <= set(project['subjects']):
            raise RuleError('У преподавателя указан неизвестный предмет')
        if teacher.get('preferred_room') and teacher['preferred_room'] not in project['rooms']:
            raise RuleError('Неизвестный предпочтительный кабинет')
    for room in project['rooms'].values():
        if not isinstance(room['capacity'], int) or room['capacity'] < 1:
            raise RuleError('Вместимость кабинета должна быть положительным целым числом')
    for field in ('daily_limits', 'weekly_limits'):
        for gid, limit in project['rules'].get(field, {}).items():
            if gid not in project['groups'] or not isinstance(limit, int) or limit < 1:
                raise RuleError('Неизвестная группа или неверный лимит нагрузки')
    for group in project["groups"].values():
        if not group["members"] or len(set(group["members"])) != len(group["members"]):
            raise RuleError("Группа должна содержать уникальные коды учеников (можно обезличенные)")
    if not 1 <= project["periods"] <= 12:
        raise RuleError("Сетка должна содержать от 1 до 12 уроков")
    for a in project["absences"]:
        if a["teacher"] not in project["teachers"] or a["start"] > a["end"]:
            raise RuleError("Некорректное отсутствие")
        date.fromisoformat(a["start"])
        date.fromisoformat(a["end"])
        if any(not 1 <= n <= project["periods"] for n in a["slots"]):
            raise RuleError("Отсутствие вне сетки уроков")
    for lessons, day in [(project["lessons"], None)] + [(v["lessons"], d) for d, v in project["days"].items()]:
        # Drafts may contain unresolved absence conflicts; they cannot be approved.
        structure = deepcopy(project)
        structure["absences"] = []
        errors = validate(structure, lessons, day)
        if errors:
            raise RuleError("\n".join(errors))


def demo_project() -> dict:
    p = empty_project()
    p.update(school="Демонстрационная школа", demo=True)
    p["subjects"] = {"math": {"name": "Математика", "equipment": []},
                     "eng": {"name": "Английский язык", "equipment": []},
                     "it": {"name": "Информатика", "equipment": ["ПК"]}}
    p["teachers"] = {
        "t1": {"name": "Иванова А. В.", "subjects": ["math"], "color": "#D9E9FF"},
        "t2": {"name": "Петров С. Н.", "subjects": ["math", "it"], "color": "#E4DBFF"},
        "t3": {"name": "Соколова Е. И.", "subjects": ["eng"], "color": "#D2F0E5"},
        "t4": {"name": "Орлова М. А.", "subjects": ["eng"], "color": "#FFE8C7"}}
    p["groups"] = {"5a": {"name": "5А · весь класс", "class": "5А", "members": [f"5a{i}" for i in range(24)]},
                   "5a1": {"name": "5А · группа 1", "class": "5А", "members": [f"5a{i}" for i in range(12)]},
                   "5a2": {"name": "5А · группа 2", "class": "5А", "members": [f"5a{i}" for i in range(12, 24)]},
                   "6a": {"name": "6А · весь класс", "class": "6А", "members": [f"6a{i}" for i in range(22)]}}
    p["rooms"] = {"101": {"name": "101", "capacity": 30, "equipment": []},
                  "102": {"name": "102", "capacity": 30, "equipment": []},
                  "204": {"name": "204 · ИКТ", "capacity": 26, "equipment": ["ПК"]}}
    for day in p["weekdays"]:
        for slot, groups, teacher, subject, room in [
            (1, ["5a"], "t1", "math", "101"), (2, ["5a1"], "t3", "eng", "101"),
            (2, ["5a2"], "t4", "eng", "102"), (3, ["5a"], "t2", "it", "204"),
            (1, ["6a"], "t2", "math", "102"), (2, ["6a"], "t1", "math", "204"),
            (3, ["6a"], "t3", "eng", "101")]:
            p["lessons"].append(dict(id=uid(), weekday=day, slot=slot, duration=1, subject=subject,
                                     groups=groups, teachers=[teacher], room=room, locked=False,
                                     status="planned", comment=""))
    return p
