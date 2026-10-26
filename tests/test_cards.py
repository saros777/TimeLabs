from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QTableWidgetItem

from timelabs.cards import Band, CARDS_ROLE, LessonDelegate, layout_cards, slot_width
from timelabs.overview import WeekTable
from timelabs.ui import Grid


def test_subgroups_divide_height_and_keep_width():
    assert slot_width(1) == slot_width(2)
    assert slot_width(1) < slot_width(3) <= slot_width(1) * 1.2
    cards = [dict(id='first'), dict(id='second')]
    bands = layout_cards(cards, 200, 100)
    assert [r.width() for _, r in bands] == [200, 200]
    assert [(r.top(), r.height()) for _, r in bands] == [(0, 50), (50, 50)]
    full = layout_cards([dict(id='shared', lane_total=3, lane_start=0, lane_span=3)], 200, 90)
    assert full[0][1].height() == 90
    assert len(full) == 1
    merged = layout_cards([dict(id='shared', lane_total=3, lane_start=1, lane_span=2)], 200, 90)
    assert merged[0][1].top() == 30
    assert merged[0][1].height() == 60


def test_delegate_draws_each_card_color_without_text_concat():
    app = QApplication.instance() or QApplication([])
    grid = Grid(None)
    grid.setRowCount(1)
    grid.setColumnCount(1)
    item = QTableWidgetItem()
    item.setData(CARDS_ROLE, [dict(id='a', color='#CCEEFF'), dict(id='b', color='#FFDDCC')])
    grid.setItem(0, 0, item)
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill(QColor('white'))
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect.setRect(0, 0, 200, 100)
    grid.itemDelegate().paint(painter, option, grid.model().index(0, 0))
    painter.end()
    assert image.pixelColor(100, 25) == QColor('#CCEEFF')
    assert image.pixelColor(100, 75) == QColor('#FFDDCC')
    grid.close()


def test_mouse_selects_individual_subgroup():
    app = QApplication.instance() or QApplication([])
    grid = Grid(None)
    grid.setRowCount(1)
    grid.setColumnCount(1)
    grid.setRowHeight(0, 100)
    item = QTableWidgetItem()
    item.setData(CARDS_ROLE, [dict(id='upper'), dict(id='lower')])
    grid.setItem(0, 0, item)
    grid.resize(400, 200)
    grid.show()
    app.processEvents()
    rect = grid.visualItemRect(item)
    assert grid.lesson_at(QPoint(rect.center().x(), rect.top() + 20)) == 'upper'
    assert grid.lesson_at(QPoint(rect.center().x(), rect.bottom() - 20)) == 'lower'
    grid.close()
