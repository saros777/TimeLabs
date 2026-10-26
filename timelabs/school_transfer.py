"""Transfer traceable school events into the editable base week."""
from copy import deepcopy
from .domain import RuleError
from .school_import import stable_id


def transfer_school(project, source):
    if source.get('errors'):
        raise RuleError('Исправьте ошибки структуры школьной книги перед импортом')
    p = deepcopy(project)
    # Explicit replacement; caller confirms and backs up before writing.
    for kind in ('subjects', 'teachers', 'groups', 'rooms'):
        p[kind] = {}
    p.update(lessons=[], days={}, absences=[], obligations=[], outbox=[])
    p['rules'] = {'daily_limits': {}, 'weekly_limits': {}, 'approved': False}
    p['source_workbook'] = deepcopy(source)
    teacher_ids = {}
    for name in source['teachers']:
        tid = stable_id('teacher', name)
        teacher_ids[name] = tid
        p['teachers'][tid] = dict(name=name, subjects=[], color='#E2EDFA')
    for number in (source.get('rooms') or {}).get('rooms', []):
        p['rooms'][number] = dict(name=number, capacity=None, equipment=[])
    for event in source['events']:
        sid = stable_id('subject', event['subject'])
        p['subjects'][sid] = dict(name=event['subject_name'], equipment=[])
        gids = []
        lanes = range(event['lane_total']) if 'весь класс' in event['profiles'] else event['lanes']
        for lane in lanes:
            gid = stable_id('group', event['school_class'], lane)
            profiles = source.get('class_profiles', {}).get(event['school_class'], [])
            label = profiles[lane] if lane < len(profiles) else ('весь класс' if event['lane_total'] == 1 else f'подгруппа {lane + 1}')
            p['groups'][gid] = dict(name=f"{event['school_class']} · {label}", **{'class': event['school_class']},
                                    members=[f'полоса:{gid}'], composition_pending=True)
            gids.append(gid)
        teachers = []
        if event.get('teacher'):
            name = event['teacher']
            tid = teacher_ids.setdefault(name, stable_id('teacher', name))
            teacher = p['teachers'].setdefault(tid, dict(name=name, subjects=[], color=event['color']))
            if sid not in teacher['subjects']:
                teacher['subjects'].append(sid)
            teachers = [tid]
        p['lessons'].append(dict(id=event['id'], weekday=event['weekday'], slot=event['slot'], duration=1,
            subject=sid, groups=gids, teachers=teachers, room=event.get('room'), locked=False,
            status='planned', comment='; '.join(event.get('review', [])),
            source_rows=event['source_rows'], teacher_candidates=event.get('teacher_candidates', []),
            color=event['color']))
    p['weekdays'] = sorted({e['weekday'] for e in source['events']}) or p['weekdays']
    p['periods'] = max(p['periods'], max((e['slot'] for e in source['events']), default=1))
    return p
