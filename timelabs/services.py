from copy import deepcopy
from datetime import date

from .domain import RuleError, absent, day_lessons, uid, validate


class Service:
    def __init__(self, store):
        self.store = store

    def edit_day(self, project, day, lessons):
        errors = validate(project, lessons, day)
        if errors:
            raise RuleError("\n".join(errors))
        old = project["days"].get(day, {})
        project["days"][day] = {"lessons": deepcopy(lessons), "status": "draft",
                                "revision": old.get("revision", 0) + 1,
                                "source": old.get("source", deepcopy(day_lessons(project, day)))}
        for item in project["outbox"]:
            if item["day"] == day and item["status"] == "queued":
                item["status"] = "stale"

    def move(self, day, lesson_id, slot, weekday=None):
        version, p = self.store.load()
        lessons = day_lessons(p, day) if day else deepcopy(p["lessons"])
        lesson = next(x for x in lessons if x["id"] == lesson_id)
        if lesson.get("locked"):
            raise RuleError("Урок закреплён")
        lesson["slot"] = slot
        if weekday:
            lesson["weekday"] = weekday
        if day:
            self.edit_day(p, day, lessons)
        else:
            errors = validate(p, lessons)
            if errors:
                raise RuleError("\n".join(errors))
            p["lessons"] = lessons
        self.store.save(p, version, "lesson.move")

    def add_absence(self, teacher, start, end, slots, reason):
        self.store.require("edit")
        date.fromisoformat(start)
        date.fromisoformat(end)
        if reason not in {"Больничный", "Отпуск", "Отгул", "Служебное отсутствие"}:
            raise RuleError("Выберите служебную категорию причины")
        version, p = self.store.load()
        p["absences"].append(dict(id=uid(), teacher=teacher, start=start, end=end, slots=slots, reason=reason))
        for d, schedule in p["days"].items():
            if start <= d <= end and validate(p, schedule["lessons"], d):
                schedule["status"] = "draft"
                for item in p["outbox"]:
                    if item["day"] == d and item["status"] == "queued":
                        item["status"] = "stale"
        self.store.save(p, version, "absence.create")

    def apply_scenario(self, day, scenario, expected_version, require_makeup=True):
        self.store.require("edit")
        version, p = self.store.load()
        if version != expected_version or scenario["day"] != day:
            raise RuleError("Сценарий устарел. Пересчитайте оба варианта")
        if not scenario["feasible"]:
            raise RuleError("Нет допустимого сценария")
        self.edit_day(p, day, scenario["lessons"])
        for lesson in scenario["lessons"]:
            if lesson.get("status") == "cancelled" and require_makeup:
                if not any(o["source_day"] == day and o["lesson"]["id"] == lesson["id"] for o in p["obligations"]):
                    p["obligations"].append(dict(id=uid(), source_day=day, lesson=deepcopy(lesson),
                                                  status="open", target_day=None, target_id=None))
        self.store.save(p, version, f"scenario.apply.{scenario['mode']}")

    def transition(self, day, target):
        permission = {"checked": "edit", "approved": "approve", "published": "publish"}[target]
        self.store.require(permission)
        version, p = self.store.load()
        if day not in p["days"]:
            self.edit_day(p, day, day_lessons(p, day))
        schedule = p["days"][day]
        required = {"checked": "draft", "approved": "checked", "published": "approved"}[target]
        if schedule["status"] != required:
            raise RuleError(f"Ожидается состояние {required}")
        errors = validate(p, schedule["lessons"], day)
        if any(x.get("status") == "cancelled" and not x.get("comment") for x in schedule["lessons"]):
            errors.append("Укажите основание отмены каждого непроведённого занятия")
        if not p["rules"].get("approved"):
            errors.append("Правила школы ещё не подтверждены администратором")
        if errors:
            raise RuleError("\n".join(errors))
        schedule["status"] = target
        if target == "published":
            p["outbox"].append(dict(id=uid(), day=day, revision=schedule["revision"], status="queued",
                                     channel="Не настроен", snapshot=deepcopy(schedule["lessons"])))
        self.store.save(p, version, f"day.{target}", permission)

    def assign_makeup(self, obligation_id, day, slot, teacher, room):
        version, p = self.store.load()
        obligation = next(o for o in p["obligations"] if o["id"] == obligation_id)
        if obligation["status"] != "open":
            raise RuleError("Обязательство уже назначено или закрыто")
        if day <= obligation["source_day"]:
            raise RuleError("Восполнение должно быть после исходной даты")
        lesson = deepcopy(obligation["lesson"])
        lesson.update(id=uid(), slot=slot, teachers=[teacher], room=room, status="makeup",
                      weekday=date.fromisoformat(day).isoweekday(), comment="Восполнение")
        lessons = day_lessons(p, day) + [lesson]
        self.edit_day(p, day, lessons)
        obligation.update(status="assigned", target_day=day, target_id=lesson["id"])
        self.store.save(p, version, "makeup.assign")

    def close_makeup(self, obligation_id):
        self.store.require("approve")
        version, p = self.store.load()
        obligation = next(o for o in p["obligations"] if o["id"] == obligation_id)
        if obligation["status"] != "assigned":
            raise RuleError("Закрыть можно только назначенное и подтверждённое занятие")
        day = obligation["target_day"]
        schedule = p["days"][day]
        if schedule["status"] not in {"approved", "published"}:
            raise RuleError("Сначала утвердите день восполнения")
        lesson = next((x for x in schedule["lessons"] if x["id"] == obligation["target_id"]), None)
        if not lesson or lesson.get("status") == "cancelled" or validate(p, schedule["lessons"], day):
            raise RuleError("Назначенное восполнение не может считаться проведённым")
        obligation["status"] = "closed"
        self.store.save(p, version, "makeup.confirm_conducted", "approve")
