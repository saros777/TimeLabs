"""Pure worker-process entry points. Results are proposals, never database writes."""
from copy import deepcopy
from itertools import product
from time import monotonic

from ortools.sat.python import cp_model

from .domain import absent, day_lessons, members, validate


def solve_day(project, day, mode="A", seconds=5):
    started = monotonic()
    lessons = day_lessons(project, day)
    model = cp_model.CpModel()
    resources, choices, costs = {}, [], []
    for index, lesson in enumerate(lessons):
        if lesson.get("status") == "cancelled":
            choices.append([])
            continue
        affected = any(absent(project, t, day, s) for t in lesson["teachers"]
                       for s in range(lesson["slot"], lesson["slot"] + lesson.get("duration", 1)))
        locked = lesson.get("locked", False)
        slots = [lesson["slot"]] if mode == "A" or locked else range(1, project["periods"] + 1)
        teacher_sets = [[t] if not affected or locked else
                        [tid for tid, teacher in project["teachers"].items() if lesson["subject"] in teacher["subjects"]]
                        for t in lesson["teachers"]]
        candidates = []
        for slot, teachers, room in product(slots, product(*teacher_sets), project["rooms"]):
            if locked and (tuple(lesson["teachers"]) != teachers or room != lesson["room"]):
                continue
            if len(set(teachers)) != len(teachers):
                continue
            candidate = {**lesson, "slot": slot, "teachers": list(teachers), "room": room}
            if validate(project, [candidate], day):
                continue
            var = model.NewBoolVar(f"l{index}_c{len(candidates)}")
            candidates.append((var, candidate))
            changed = candidate != lesson
            cost = 30 * changed + 8 * (slot != lesson["slot"]) + 2 * (room != lesson["room"])
            for tid in teachers:
                preferred = project["teachers"][tid].get("preferred_room")
                if preferred and preferred != room:
                    cost += 1
            costs.append(cost * var)
            for period in range(slot, slot + lesson.get("duration", 1)):
                keys = [(period, "t", t) for t in teachers] + [(period, "r", room)]
                keys += [(period, "p", p) for p in members(project, lesson["groups"])]
                for key in keys:
                    resources.setdefault(key, []).append(var)
        unplaced = model.NewBoolVar(f"unplaced{index}")
        if not affected or locked:
            model.Add(unplaced == 0)
        model.Add(sum(v for v, _ in candidates) + unplaced == 1)
        # Lexicographic first goal: no uncovered lesson, then stability/preferences.
        costs.append(unplaced * (1000 * (len(lessons) + 1)))
        choices.append((candidates, unplaced))
    for variables in resources.values():
        model.Add(sum(variables) <= 1)
    # Daily group caps count actual occupied student periods, including overlaps.
    for gid, limit in project["rules"]["daily_limits"].items():
        for pupil in project["groups"][gid]["members"]:
            model.Add(sum(var * candidate.get("duration", 1)
                          for choice in choices if choice for var, candidate in choice[0]
                          if pupil in members(project, candidate["groups"])) <= limit)
    model.Minimize(sum(costs))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_search_workers = 2
    solver.parameters.random_seed = 42
    status = solver.Solve(model)
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    result = []
    if feasible:
        for original, choice in zip(lessons, choices):
            if not choice:
                result.append(deepcopy(original))
            elif solver.Value(choice[1]):
                result.append({**original, "status": "cancelled", "comment": "Нет допустимого назначения; решение требует подтверждения"})
            else:
                result.append(next(candidate for var, candidate in choice[0] if solver.Value(var)))
        errors = validate(project, result, day)
        if errors:
            return dict(mode=mode, day=day, feasible=False, lessons=[], metrics={}, diagnostic="; ".join(errors))
    changed = [(a, b) for a, b in zip(lessons, result) if a != b]
    metrics = {"Изменено уроков": len(changed),
               "Непроведено": sum(x.get("status") == "cancelled" for x in result),
               "Затронуто групп": len({g for a, b in changed for g in a["groups"]}),
               "Затронуто учителей": len({t for a, b in changed for t in a["teachers"] + b["teachers"]}),
               "Смен кабинета": sum(a["room"] != b["room"] for a, b in changed),
               "Переносов": sum(a["slot"] != b["slot"] for a, b in changed),
               "Жёстких нарушений": 0 if feasible else None}
    return dict(mode=mode, day=day, feasible=feasible, lessons=result, metrics=metrics,
                seconds=round(monotonic() - started, 2), status=solver.StatusName(status),
                diagnostic="" if feasible else "Нет допустимого решения в лимит времени. Проверьте закреплённые уроки, отсутствия и ресурсы.")


def solve_pair(project, day):
    return [solve_day(project, day, mode) for mode in ("A", "B")]
