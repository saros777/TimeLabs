"""Card geometry shared by daily editor and compact weekly overview.
Subgroups divide HEIGHT, never create additional horizontal lesson columns.
"""
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle

CARDS_ROLE = int(Qt.ItemDataRole.UserRole) + 1
PREVIEW_ROLE = int(Qt.ItemDataRole.UserRole) + 2


@dataclass(frozen=True)
class Band:
    start: int
    span: int
    total: int

    def rect(self, width, height):
        return QRectF(0, height * self.start / self.total, width, height * self.span / self.total)


def slot_width(branches=1, base=52):
    """Two branches have exactly the same width as an undivided lesson."""
    return round(base * 1.15) if branches >= 3 else base


def layout_cards(cards, width, height):
    result = []
    for index, card in enumerate(cards):
        total = card.get('lane_total', len(cards))
        start = card.get('lane_start', index)
        span = card.get('lane_span', 1)
        if total < 1 or start < 0 or span < 1 or start + span > total:
            raise ValueError('Invalid subgroup card geometry')
        result.append((card, Band(start, span, total).rect(width, height)))
    return result


class LessonDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        cards = index.data(CARDS_ROLE)
        if not cards:
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setClipRect(option.rect)
        for card, local in layout_cards(cards, option.rect.width(), option.rect.height()):
            rect = local.translated(option.rect.x(), option.rect.y())
            color = QColor(card.get('color', '#E2EDFA'))
            if not color.isValid():
                color = QColor('#E2EDFA')
            painter.fillRect(rect.adjusted(1, 1, -1, -1), color)
            painter.setPen(QPen(QColor('#BBC7D8'), 0.5))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            painter.setPen(QColor('#12263E'))
            font = QFont(option.font)
            font.setPointSizeF(9 if card.get('compact') else 10)
            painter.setFont(font)
            if card.get('compact') and 'right' in card:
                font.setPointSizeF(7.5)
                painter.setFont(font)
                metrics=painter.fontMetrics()
                right=str(card['right'])
                right_width=min(metrics.horizontalAdvance(right)+4,rect.width()*0.4)
                label=metrics.elidedText(card.get('label',''),Qt.TextElideMode.ElideRight,max(1,int(rect.width()-right_width-5)))
                painter.drawText(rect.adjusted(3,0,-right_width,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,label)
                painter.drawText(rect.adjusted(0,0,-3,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight,right)
                if card.get('cancelled'):
                    painter.setPen(QPen(QColor('#9F3643'),1))
                    painter.drawLine(rect.left()+2,rect.center().y(),rect.right()-2,rect.center().y())
                continue
            lines = card.get('label', '').split('\n')
            metrics = painter.fontMetrics()
            line_height = metrics.height()
            fits = max(1, int((rect.height() - 2) / line_height))
            displayed = lines[:fits]
            top = rect.top() + max(0, (rect.height() - len(displayed) * line_height) / 2)
            for n, text in enumerate(displayed):
                text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width() - 6))
                painter.drawText(QRectF(rect.left() + 3, top + n * line_height, rect.width() - 6, line_height),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            if card.get('review'):
                painter.setPen(QPen(QColor('#986000'), 2))
                painter.drawLine(rect.topLeft(), rect.topRight())
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QPen(QColor('#145DC3'), 2))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
        preview = index.data(PREVIEW_ROLE)
        if preview is not None:
            painter.setPen(QPen(QColor('#16733A' if preview else '#B72828'), 3))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
        painter.restore()
