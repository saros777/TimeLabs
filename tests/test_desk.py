from copy import deepcopy
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, Qt
from timelabs.cards import CARDS_ROLE
from timelabs.desk import DeskTable
from timelabs.domain import demo_project


def test_horizontal_week_resources_and_subgroup_hit_targets():
    app=QApplication.instance() or QApplication([])
    p=demo_project()
    desk=DeskTable()
    desk.populate(p,'Классы',None,'',40,25,lambda e:e['subject'])
    assert desk.rowCount()==2 and desk.columnCount()==45
    assert desk.times[10]==(None,2,2)
    item=desk.item(0,1)
    cards=item.data(CARDS_ROLE)
    assert len(cards)==2 and cards[0]['lane_total']==2
    desk.resize(1000,300);desk.show();app.processEvents()
    rect=desk.visualItemRect(item)
    assert desk.lesson_at(QPoint(rect.center().x(),rect.top()+3))==cards[0]['id']
    assert desk.lesson_at(QPoint(rect.center().x(),rect.bottom()-3))==cards[1]['id']
    desk.populate(p,'Учителя','2026-10-28','',40,25,lambda e:e['subject'])
    assert desk.rowCount()==4
    assert desk.times[0][0]=='2026-10-26'
    assert desk.times[36][0]=='2026-10-30'
    desk.close()


def test_nonadjacent_profiles_keep_single_identity_and_empty_middle():
    app=QApplication.instance() or QApplication([])
    p=demo_project()
    p['lessons']=[p['lessons'][0]]
    e=p['lessons'][0]
    original=e['groups'][0]
    p['groups'][original].update(lane_index=0,lane_total=3)
    p['groups']['third']={**deepcopy(p['groups'][original]),'lane_index':2}
    e['groups'].append('third')
    desk=DeskTable()
    desk.populate(p,'Классы',None,'',40,25,lambda e:e['subject'])
    cards=desk.item(0,0).data(CARDS_ROLE)
    assert len(cards)==2
    assert {c['id'] for c in cards}=={e['id']}
    assert [c['lane_start'] for c in cards]==[0,2]
    desk.close()
