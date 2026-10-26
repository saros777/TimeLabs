from copy import deepcopy
from timelabs.teacher_import import resolve_teachers


def event(key, candidates, subject='math', slot=1, teacher=None):
    return dict(id=key,teacher=teacher,teacher_candidates=candidates,subject=subject,color='#DDEEFF',weekday=1,slot=slot,review=['Преподаватель не подтверждён'])


def test_snapshot_exact_assignment_has_provenance_and_does_not_mutate():
    source=dict(events=[event('one',['Иванова'])],summary={})
    old=deepcopy(source)
    result=resolve_teachers(source)
    assert source==old
    assert result['events'][0]['teacher']=='Иванова'
    assert 'класса, дня и урока' in result['events'][0]['teacher_source']


def test_ambiguous_subjects_and_double_booking_stay_unassigned():
    source=dict(events=[event('a',['А','Б']),event('b',['А','Б']),
                        event('c',['В'],slot=2),event('d',['В'],slot=2)],summary={})
    result=resolve_teachers(source)
    assert all(e['teacher'] is None for e in result['events'])


def test_subject_cross_reference_uses_only_teachers_in_snapshot_slot():
    source=dict(events=[event('seed',['А'],slot=1),event('other',['Б'],subject='eng',slot=2),
                        event('target',['А','Б'],slot=3),event('unknown',['Б','В'],subject='unknown',slot=4)],summary={})
    # Make color neutral/ambiguous; it cannot decide the target.
    result=resolve_teachers(source)
    assert result['events'][2]['teacher']=='А'
    assert result['events'][3]['teacher'] is None
