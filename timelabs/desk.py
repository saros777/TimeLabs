"""Editable horizontal weekly timetable, shared by every resource view."""
from collections import defaultdict
from datetime import date, timedelta
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QColor, QPainter, QDrag
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem
from .cards import CARDS_ROLE, LessonDelegate, layout_cards
from .domain import day_lessons
from .school_import import class_sort

DAY_NAMES = ['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье']


class TimeHeader(QHeaderView):
    def __init__(self, parent):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.days = []
        self.periods = 9
        self.setFixedHeight(48)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        self.setMinimumSectionSize(28)
        self.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        for i, title in enumerate(self.days):
            first, last = i*self.periods, (i+1)*self.periods-1
            left = self.sectionViewportPosition(first)
            right = self.sectionViewportPosition(last)+self.sectionSize(last)
            rect = QRect(left, 0, right-left, 24)
            painter.fillRect(rect, QColor('#EDF2F8'))
            painter.setPen(QColor('#ADBFD5'))
            painter.drawRect(rect.adjusted(0,0,-1,-1))
            painter.setPen(QColor('#17344F'))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, title)
        painter.end()


class DeskTable(QTableWidget):
    lesson_opened = Signal(str, object, int)
    lesson_moved = Signal(str, object, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeader(TimeHeader(self))
        self.setItemDelegate(LessonDelegate(self))
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.hit = None
        self.times = []
        self.cellDoubleClicked.connect(self.open_cell)
        self.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalHeader().setMinimumWidth(48)

    def lesson_at(self, pos):
        item = self.itemAt(pos)
        if not item:
            return None
        rect = self.visualItemRect(item)
        for card, band in layout_cards(item.data(CARDS_ROLE) or [], rect.width(), rect.height()):
            if band.contains(pos.x()-rect.x(), pos.y()-rect.y()):
                return card['id']

    def mousePressEvent(self, event):
        self.hit = self.lesson_at(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.hit = self.lesson_at(event.position().toPoint())
        super().mouseDoubleClickEvent(event)

    def open_cell(self, row, col):
        item = self.item(row,col)
        ids = item.data(Qt.ItemDataRole.UserRole) if item else []
        selected = self.hit if self.hit in (ids or []) else ids[0] if ids and len(ids)==1 else None
        if selected:
            day, weekday, slot = self.times[col]
            self.lesson_opened.emit(selected, day, weekday)

    def startDrag(self, actions):
        if not self.hit:
            return
        self.drag_day=self.times[self.currentColumn()][0]
        mime = QMimeData()
        mime.setData('application/x-timelabs-week', self.hit.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('application/x-timelabs-week'):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        col = self.columnAt(int(event.position().x()))
        if col >= 0 and event.mimeData().hasFormat('application/x-timelabs-week'):
            day, weekday, slot = self.times[col]
            self.lesson_moved.emit(bytes(event.mimeData().data('application/x-timelabs-week')).decode(), day, weekday, slot)
            event.acceptProposedAction()

    def populate(self, p, view, day, search, width, row_height, describe):
        source=p.get('source_workbook',{})
        source_by_id={e['id']:e for e in source.get('events',[])}
        kind = {'Учителя':'teachers', 'Кабинеты':'rooms', 'Группы':'groups'}.get(view)
        resources = [(k,v['name']) for k,v in p[kind].items()] if kind else [(c,c) for c in sorted({g['class'] for g in p['groups'].values()},key=class_sort)]
        self.clear()
        self.setRowCount(len(resources))
        self.setColumnCount(len(p['weekdays'])*p['periods'])
        self.setVerticalHeaderLabels([name for key,name in resources])
        self.setHorizontalHeaderLabels(['\n'+str(i%p['periods']+1) for i in range(self.columnCount())])
        self.times=[]
        labels=[]
        monday = date.fromisoformat(day)-timedelta(days=date.fromisoformat(day).weekday()) if day else None
        slots=defaultdict(list)
        for weekday in p['weekdays']:
            concrete = (monday+timedelta(days=weekday-1)).isoformat() if monday else None
            labels.append(DAY_NAMES[weekday-1]+('  '+date.fromisoformat(concrete).strftime('%d.%m') if concrete else ''))
            lessons=day_lessons(p,concrete) if concrete else [e for e in p['lessons'] if e['weekday']==weekday]
            for lesson in lessons:
                if search and search.casefold() not in describe(lesson).casefold():continue
                keys=lesson[kind] if kind in ('teachers','groups') else [lesson['room']] if kind=='rooms' else {p['groups'][g]['class'] for g in lesson['groups']}
                for key in keys:
                    for period in range(lesson['slot'],lesson['slot']+lesson.get('duration',1)):
                        slots[(key,weekday,period)].append(lesson)
            for period in range(1,p['periods']+1):self.times.append((concrete,weekday,period))
        self.horizontalHeader().days=labels
        self.horizontalHeader().periods=p['periods']
        for col in range(self.columnCount()):self.setColumnWidth(col,width)
        for row,(key,name) in enumerate(resources):
            total=max((g.get('lane_total',source.get('class_lanes',{}).get(key,1)) for g in p['groups'].values() if g['class']==key),default=1) if not kind else 1
            self.setRowHeight(row,max(row_height,total*17))
            for col,(_,weekday,period) in enumerate(self.times):
                lessons=slots[(key,weekday,period)]
                item=QTableWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole,[e['id'] for e in lessons])
                cards=[]
                for index,e in enumerate(lessons):
                    subject=p['subjects'][e['subject']]
                    color=p['teachers'][e['teachers'][0]].get('color','#DCE8F6') if e['teachers'] else e.get('color','#FFF0D2')
                    room=p['rooms'].get(e['room'],{}).get('name','—')
                    card=dict(id=e['id'], label=subject.get('short',source_by_id.get(e['id'],{}).get('subject',subject['name'])), right=room, color=color,
                              compact=True,tooltip=describe(e),cancelled=e.get('status')=='cancelled')
                    if not kind and all('lane_index' in p['groups'][g] for g in e['groups']):
                        lanes=sorted({p['groups'][g].get('lane_index',0) for g in e['groups'] if p['groups'][g]['class']==key})
                        runs=[]
                        for lane in lanes:
                            if runs and lane==runs[-1][-1]+1:runs[-1].append(lane)
                            else:runs.append([lane])
                        for run in runs:cards.append({**card,'lane_start':run[0],'lane_span':len(run),'lane_total':total})
                    elif not kind and e['id'] in source_by_id:
                        event=source_by_id[e['id']]
                        for run in event['lane_runs']:
                            cards.append({**card,'lane_start':run[0],'lane_span':len(run),'lane_total':event['lane_total']})
                    else:cards.append({**card,'lane_start':index,'lane_total':len(lessons)})
                item.setData(CARDS_ROLE,cards)
                item.setToolTip('\n\n'.join(describe(e) for e in lessons) if lessons else 'Свободный урок')
                self.setItem(row,col,item)
        self.horizontalHeader().viewport().update()


STYLE = '''
QMainWindow,QDialog {background:#F3F5F8;color:#233B55;}
QWidget {font-family:"Segoe UI";font-size:12px;}
QFrame#navigation {background:#19334D;border:0;}
QLabel#brand {color:white;font-size:20px;font-weight:700;padding:12px 20px;}
QFrame#navigation QPushButton {background:transparent;color:#CDD9E6;border:0;border-radius:0;padding:19px 15px;font-weight:600;}
QFrame#navigation QPushButton:checked {background:#29445E;color:white;border-bottom:3px solid #5A9DF5;}
QLabel#heading {font-size:23px;font-weight:700;color:#233B55;}
QPushButton {background:white;border:1px solid #D3DCE8;border-radius:4px;padding:8px 12px;color:#253E5B;}
QPushButton:hover {background:#EAF1FA;border-color:#AABED8;}
QPushButton#primary {background:#225BD2;color:white;border:1px solid #225BD2;font-weight:600;}
QLineEdit,QComboBox,QDateEdit,QSpinBox {background:white;border:1px solid #D3DCE8;border-radius:4px;padding:6px;color:#253E5B;}
QTableWidget {background:white;gridline-color:#D6DFEC;selection-background-color:#DDEBFF;}
QHeaderView::section {background:#F0F4FA;color:#183653;border:1px solid #D6DFEC;padding:3px;font-size:10px;}
QScrollBar:vertical {background:#F0F3F7;width:11px;} QScrollBar::handle:vertical {background:#ABB9C9;min-height:25px;border-radius:4px;}
QLabel#muted {color:#728399;}
'''
