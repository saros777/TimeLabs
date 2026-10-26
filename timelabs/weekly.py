"""Weekly placement from explicit lesson requirements entered in the base editor.
One record = one occurrence; duration = consecutive periods, never teacher hours.
"""
from collections import defaultdict
from copy import deepcopy

from ortools.sat.python import cp_model

from .domain import members, validate


def generate_week(project, seconds=20):
    model = cp_model.CpModel()
    choices, busy, costs, daily, weekly = [], defaultdict(list), [], defaultdict(list), defaultdict(list)
    for index, original in enumerate(project['lessons']):
        if original.get('status') == 'cancelled':
            choices.append([])
            continue
        options = []
        days = [original['weekday']] if original.get('locked') else project['weekdays']
        slots = [original['slot']] if original.get('locked') else range(1, project['periods'] + 1)
        rooms = [original['room']] if original.get('locked') else project['rooms']
        pupils = members(project, original['groups'])
        for day in days:
            for slot in slots:
                for room in rooms:
                    lesson = {**original, 'weekday': day, 'slot': slot, 'room': room}
                    if validate(project, [lesson]):
                        continue
                    variable = model.NewBoolVar(f'l{index}_{day}_{slot}_{room}')
                    options.append((variable, lesson))
                    costs.append(variable * (20 * (day != original['weekday']) + 5 * (slot != original['slot']) + (room != original['room'])))
                    for period in range(slot, slot + lesson.get('duration', 1)):
                        for kind, ids in [('t', lesson['teachers']), ('r', [room]), ('p', pupils)]:
                            for rid in ids:
                                busy[(day, period, kind, rid)].append(variable)
                    for pupil in pupils:
                        daily[(day, pupil)].append(variable * lesson.get('duration', 1))
                        weekly[pupil].append(variable * lesson.get('duration', 1))
        model.Add(sum(v for v, _ in options) == 1)
        choices.append(options)
    for variables in busy.values():
        model.Add(sum(variables) <= 1)
    for gid, group in project['groups'].items():
        for pupil in group['members']:
            if gid in project['rules']['daily_limits']:
                for day in project['weekdays']:
                    model.Add(sum(daily[(day, pupil)]) <= project['rules']['daily_limits'][gid])
            if gid in project['rules'].get('weekly_limits', {}):
                model.Add(sum(weekly[pupil]) <= project['rules']['weekly_limits'][gid])
    model.Minimize(sum(costs))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_search_workers = 2
    status = solver.Solve(model)
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    lessons = []
    if feasible:
        for original, options in zip(project['lessons'], choices):
            lessons.append(next(l for v, l in options if solver.Value(v)) if options else deepcopy(original))
    errors = validate(project, lessons) if feasible else []
    return {'feasible': feasible and not errors, 'lessons': lessons, 'status': solver.StatusName(status),
            'diagnostic': '\n'.join(errors) if errors else '' if feasible else 'Не удалось разместить все занятия. Проверьте закрепления, лимиты, доступность и число помещений.'}
