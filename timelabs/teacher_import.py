"""Cross-reference class/period snapshots, retaining evidence for each assignment."""
from collections import defaultdict
from copy import deepcopy
from .school_import import stable_id


def resolve_teachers(source):
    result = deepcopy(source)
    events = result['events']
    # Only exact class/day/period candidates from the teacher snapshot are used.
    by_color, by_subject = defaultdict(set), defaultdict(set)
    for e in events:
        teacher = e.get('teacher')
        if not teacher and len(e.get('teacher_candidates', [])) == 1:
            teacher = e['teacher_candidates'][0]
        if teacher:
            by_color[e['color']].add(teacher)
            by_subject[e['subject']].add(teacher)
    proposed = {}
    for e in events:
        if e.get('teacher'):
            continue
        candidates = set(e.get('teacher_candidates', []))
        reason = 'Единственное совпадение класса, дня и урока на листе «Учителя — снимок»'
        if len(candidates) != 1:
            color = by_color.get(e['color'], set())
            compatible = candidates & color
            if len(color) == 1 and len(compatible) == 1:
                candidates = compatible
                reason = 'Снимок преподавателей и однозначное соответствие цвета из назначений'
            else:
                compatible = candidates & by_subject.get(e['subject'], set())
                if len(compatible) == 1:
                    candidates = compatible
                    reason = 'Снимок преподавателей и предмет из однозначных назначений этого файла'
        if len(candidates) == 1:
            proposed[e['id']] = (next(iter(candidates)), reason)
    # A teacher cannot be auto-assigned twice in a slot. Ambiguity stays visible.
    busy = defaultdict(list)
    for e in events:
        t = e.get('teacher') or proposed.get(e['id'], (None,))[0]
        if t:
            busy[(e['weekday'], e['slot'], t)].append(e['id'])
    for e in events:
        if e['id'] not in proposed:
            continue
        teacher, reason = proposed[e['id']]
        if len(busy[(e['weekday'], e['slot'], teacher)]) != 1:
            continue
        e.update(teacher=teacher, teacher_source=reason, assignment_inferred=True)
        e['review'] = [r for r in e.get('review', []) if r != 'Преподаватель не подтверждён']
    result['summary']['confirmed_teacher_events'] = sum(bool(e.get('teacher')) for e in events)
    result['summary']['extracted_teacher_events'] = sum(e.get('assignment_inferred', False) for e in events)
    return result
