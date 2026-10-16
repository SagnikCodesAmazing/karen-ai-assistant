"""
KAREN Voice Assistant HUD (Heads-Up Display)
=============================================
A sleek, glassmorphic card overlay for the KAREN voice assistant.
Sits in the bottom-right corner of the desktop, appears when the
wake word is detected, and shows state / transcript / response.

Uses PySide6 for native Windows desktop integration.
"""

import sys
import math
import random
from PySide6.QtWidgets import QApplication, QWidget, QGraphicsOpacityEffect
from PySide6.QtCore import (
    Qt, QTimer, Signal, Slot, QRectF, QPointF,
    QPropertyAnimation, QEasingCurve, Property, QRect
)
from PySide6.QtGui import (
    QFont, QFontDatabase, QColor, QPainter, QBrush, QPen,
    QLinearGradient, QPainterPath, QRadialGradient, QFontMetrics
)


# ──────────────────────────────────────────────────────────────
#  Design tokens
# ──────────────────────────────────────────────────────────────

CARD_WIDTH        = 310
CARD_MIN_HEIGHT   = 150
CARD_MAX_HEIGHT   = 260
CARD_RADIUS       = 14
CARD_MARGIN       = 24          # distance from screen edge

BG_COLOR          = QColor(18, 22, 32, 225)      # dark semi-transparent
BORDER_COLOR      = QColor(255, 255, 255, 18)     # subtle white border
ACCENT_CYAN       = QColor(0, 210, 235)           # listening accent
ACCENT_GREEN      = QColor(0, 230, 130)           # speaking accent
ACCENT_AMBER      = QColor(255, 190, 50)          # thinking accent
MUTED_TEXT        = QColor(140, 150, 170)          # secondary text
BRIGHT_TEXT       = QColor(230, 235, 245)          # primary text
DIM_TEXT          = QColor(90, 100, 120)           # very dim text

BAR_COUNT         = 36
BAR_GAP           = 3
BAR_WIDTH_PX      = 2
BAR_MAX_HEIGHT    = 32
BAR_AREA_TOP      = 52
WAVEFORM_PADDING  = 20

FONT_MONO         = "Consolas"
FONT_BODY         = "Segoe UI"

# Animation
FPS               = 60
FRAME_MS          = int(1000 / FPS)
SLIDE_DURATION_MS = 280


# ──────────────────────────────────────────────────────────────
#  State → visual mapping
# ──────────────────────────────────────────────────────────────

STATE_VISUALS = {
    "IDLE": {
        "label": "IDLE",
        "accent": MUTED_TEXT,
        "bar_energy": 0.0,
    },
    "LISTENING": {
        "label": "LISTENING",
        "accent": ACCENT_CYAN,
        "bar_energy": 0.65,
    },
    "THINKING": {
        "label": "PROCESSING",
        "accent": ACCENT_AMBER,
        "bar_energy": 0.25,
    },
    "SPEAKING": {
        "label": "SPEAKING",
        "accent": ACCENT_GREEN,
        "bar_energy": 0.85,
    },
    "ERROR": {
        "label": "ERROR",
        "accent": QColor(230, 60, 60),
        "bar_energy": 0.0,
    },
}


class KarenHUD(QWidget):
    """
    Glassmorphic card overlay for KAREN.

    Thread-safe public API (call from any thread):
        hud.state_changed.emit("LISTENING")
        hud.transcript_updated.emit("What broke last night?")
        hud.response_updated.emit("Three build failures.")
    """

    # ── Signals (thread-safe bridge to GUI thread) ──
    state_changed      = Signal(str)
    transcript_updated = Signal(str)
    response_updated   = Signal(str)

    def __init__(self):
        super().__init__()

        # State
        self.current_state   = "IDLE"
        self.transcript_text = ""
        self.response_text   = ""
        self.drag_position   = None

        # Waveform bar heights (normalised 0-1)
        self._bar_targets    = [0.0] * BAR_COUNT
        self._bar_current    = [0.0] * BAR_COUNT
        self._bar_phase      = 0.0

        # Computed card height (changes when response text is present)
        self._card_height    = CARD_MIN_HEIGHT

        # Slide animation y-offset (0 = fully visible)
        self._slide_offset   = CARD_MIN_HEIGHT + CARD_MARGIN

        # Setup
        self._setup_window()
        self._setup_animation()
        self._connect_signals()

        # Start hidden
        self.hide()

    # ──────────────────────────────────────────────────────────
    #  Window setup
    # ──────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.setFixedWidth(CARD_WIDTH)
        self.setMinimumHeight(CARD_MIN_HEIGHT)
        self.setMaximumHeight(CARD_MAX_HEIGHT + 60)

        self._reposition()

    def _reposition(self):
        """Place the widget at the bottom-right of the primary screen."""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + geo.width() - CARD_WIDTH - CARD_MARGIN
        y = geo.y() + geo.height() - self._card_height - CARD_MARGIN
        self.move(x, y)

    # ──────────────────────────────────────────────────────────
    #  Slide offset property (for QPropertyAnimation)
    # ──────────────────────────────────────────────────────────

    def _get_slide_offset(self):
        return self._slide_offset

    def _set_slide_offset(self, val):
        self._slide_offset = val
        self._reposition_with_offset()
        self.update()

    slideOffset = Property(float, _get_slide_offset, _set_slide_offset)

    def _reposition_with_offset(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + geo.width() - CARD_WIDTH - CARD_MARGIN
        base_y = geo.y() + geo.height() - self._card_height - CARD_MARGIN
        self.move(x, int(base_y + self._slide_offset))

    # ──────────────────────────────────────────────────────────
    #  Animation
    # ──────────────────────────────────────────────────────────

    def _setup_animation(self):
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(FRAME_MS)

        # Slide animation
        self._slide_anim = QPropertyAnimation(self, b"slideOffset")
        self._slide_anim.setDuration(SLIDE_DURATION_MS)
        self._slide_anim.setEasingCurve(QEasingCurve.OutCubic)

    def _tick(self):
        """Per-frame animation update."""
        vis = STATE_VISUALS.get(self.current_state, STATE_VISUALS["IDLE"])
        energy = vis["bar_energy"]

        self._bar_phase += 0.12

        # Generate new random targets based on energy
        for i in range(BAR_COUNT):
            phase = self._bar_phase + i * 0.35
            base = energy * (0.3 + 0.7 * abs(math.sin(phase)))
            noise = random.uniform(-0.15, 0.15) * energy
            self._bar_targets[i] = max(0.0, min(1.0, base + noise))

        # Smooth interpolation towards targets
        lerp = 0.18
        for i in range(BAR_COUNT):
            self._bar_current[i] += (self._bar_targets[i] - self._bar_current[i]) * lerp

        self.update()

    # ──────────────────────────────────────────────────────────
    #  Signals → slots
    # ──────────────────────────────────────────────────────────

    def _connect_signals(self):
        self.state_changed.connect(self._on_state_changed)
        self.transcript_updated.connect(self._on_transcript_updated)
        self.response_updated.connect(self._on_response_updated)

    @Slot(str)
    def _on_state_changed(self, state):
        if state not in STATE_VISUALS:
            return

        prev = self.current_state
        self.current_state = state

        if state == "IDLE":
            # Clear text and slide out
            self._slide_out()
        else:
            if state == "LISTENING":
                # New interaction — clear previous text
                self.transcript_text = ""
                self.response_text = ""
            self._recalc_height()
            if prev == "IDLE" or not self.isVisible():
                self._slide_in()
            else:
                self._reposition()
            self.raise_()

        self.update()

    @Slot(str)
    def _on_transcript_updated(self, text):
        self.transcript_text = text
        self._recalc_height()
        self._reposition()
        self.update()

    @Slot(str)
    def _on_response_updated(self, text):
        self.response_text = text
        self._recalc_height()
        self._reposition()
        self.update()

    # ──────────────────────────────────────────────────────────
    #  Show / hide with slide animation
    # ──────────────────────────────────────────────────────────

    def _slide_in(self):
        self._slide_offset = self._card_height + CARD_MARGIN
        self.show()
        self.raise_()
        self._slide_anim.stop()
        self._slide_anim.setStartValue(float(self._card_height + CARD_MARGIN))
        self._slide_anim.setEndValue(0.0)
        self._slide_anim.start()

    def _slide_out(self):
        self._slide_anim.stop()
        self._slide_anim.setStartValue(float(self._slide_offset))
        self._slide_anim.setEndValue(float(self._card_height + CARD_MARGIN))
        self._slide_anim.finished.connect(self._on_slide_out_done)
        self._slide_anim.start()

    def _on_slide_out_done(self):
        self.hide()
        self.transcript_text = ""
        self.response_text = ""
        try:
            self._slide_anim.finished.disconnect(self._on_slide_out_done)
        except RuntimeError:
            pass

    # ──────────────────────────────────────────────────────────
    #  Height calculation
    # ──────────────────────────────────────────────────────────

    def _recalc_height(self):
        h = CARD_MIN_HEIGHT  # header + waveform + small padding

        if self.transcript_text:
            h += 22  # one line of transcript

        if self.response_text:
            # Estimate wrapped lines
            fm = QFontMetrics(QFont(FONT_BODY, 9))
            avail = CARD_WIDTH - WAVEFORM_PADDING * 2 - 14  # border + padding
            lines = 1
            for paragraph in self.response_text.split("\n"):
                rect = fm.boundingRect(
                    QRect(0, 0, avail, 1000),
                    Qt.TextWordWrap,
                    paragraph
                )
                lines += max(1, rect.height() // fm.height())
            h += int(lines * fm.height()) + 16

        h = max(CARD_MIN_HEIGHT, min(CARD_MAX_HEIGHT + 60, h))
        self._card_height = h
        self.setFixedHeight(h)

    # ──────────────────────────────────────────────────────────
    #  Paint
    # ──────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        vis = STATE_VISUALS.get(self.current_state, STATE_VISUALS["IDLE"])
        accent = vis["accent"]

        self._paint_card_bg(painter, accent)
        self._paint_header(painter, vis, accent)
        self._paint_waveform(painter, accent)
        self._paint_transcript(painter)
        self._paint_response(painter, accent)

        painter.end()

    # ── Card background ──

    def _paint_card_bg(self, p: QPainter, accent: QColor):
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)

        # Fill
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(BG_COLOR))
        p.drawPath(path)

        # Subtle top highlight gradient
        highlight = QLinearGradient(0, 0, 0, 40)
        highlight.setColorAt(0, QColor(255, 255, 255, 8))
        highlight.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(highlight))
        p.drawPath(path)

        # Border
        pen = QPen(BORDER_COLOR, 1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), CARD_RADIUS, CARD_RADIUS)

        # Accent glow at top
        glow = QLinearGradient(0, 0, self.width(), 0)
        glow_color = QColor(accent)
        glow_color.setAlpha(25)
        glow.setColorAt(0, QColor(0, 0, 0, 0))
        glow.setColorAt(0.3, glow_color)
        glow.setColorAt(0.7, glow_color)
        glow.setColorAt(1, QColor(0, 0, 0, 0))

        glow_path = QPainterPath()
        glow_path.addRoundedRect(QRectF(0, 0, self.width(), 3), CARD_RADIUS, CARD_RADIUS)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawPath(glow_path)

    # ── Header: ◆ STATE · ON-DEVICE ──

    def _paint_header(self, p: QPainter, vis: dict, accent: QColor):
        left_x = WAVEFORM_PADDING
        y = 22

        # Diamond icon
        diamond_font = QFont(FONT_BODY, 7)
        p.setFont(diamond_font)
        p.setPen(QPen(accent))
        p.drawText(left_x, y, "◆")

        # State label
        label_font = QFont(FONT_MONO, 9, QFont.Bold)
        label_font.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        p.setFont(label_font)
        p.setPen(QPen(accent))
        p.drawText(left_x + 16, y, vis["label"])

        # ON-DEVICE badge (right-aligned)
        badge_font = QFont(FONT_MONO, 7)
        badge_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(badge_font)
        p.setPen(QPen(DIM_TEXT))
        badge_text = "ON-DEVICE"
        fm = QFontMetrics(badge_font)
        badge_w = fm.horizontalAdvance(badge_text)
        p.drawText(self.width() - WAVEFORM_PADDING - badge_w, y, badge_text)

    # ── Waveform bars ──

    def _paint_waveform(self, p: QPainter, accent: QColor):
        area_left = WAVEFORM_PADDING
        area_width = self.width() - 2 * WAVEFORM_PADDING
        center_y = BAR_AREA_TOP + BAR_MAX_HEIGHT // 2 + 8

        total_bar_width = BAR_COUNT * (BAR_WIDTH_PX + BAR_GAP) - BAR_GAP
        start_x = area_left + (area_width - total_bar_width) / 2

        for i in range(BAR_COUNT):
            h = max(2, int(self._bar_current[i] * BAR_MAX_HEIGHT))
            x = start_x + i * (BAR_WIDTH_PX + BAR_GAP)
            top = center_y - h // 2
            bottom = center_y + h // 2

            # Gradient per bar: bright at center, dim at tips
            grad = QLinearGradient(x, top, x, bottom)
            bar_color = QColor(accent)
            bar_color.setAlpha(200)
            dim_color = QColor(accent)
            dim_color.setAlpha(60)

            grad.setColorAt(0.0, dim_color)
            grad.setColorAt(0.45, bar_color)
            grad.setColorAt(0.55, bar_color)
            grad.setColorAt(1.0, dim_color)

            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(x, top, BAR_WIDTH_PX, h), 1, 1)

        # Subtle center line
        p.setPen(QPen(QColor(255, 255, 255, 15), 0.5))
        p.drawLine(
            QPointF(start_x - 4, center_y),
            QPointF(start_x + total_bar_width + 4, center_y)
        )

    # ── Transcript text ──

    def _paint_transcript(self, p: QPainter):
        if not self.transcript_text:
            return

        y_start = BAR_AREA_TOP + BAR_MAX_HEIGHT + 20

        font = QFont(FONT_BODY, 9)
        font.setItalic(True)
        p.setFont(font)
        p.setPen(QPen(MUTED_TEXT))

        text = f'"{self.transcript_text}"'
        fm = QFontMetrics(font)
        elided = fm.elidedText(text, Qt.ElideRight, CARD_WIDTH - 2 * WAVEFORM_PADDING)
        p.drawText(WAVEFORM_PADDING, y_start, elided)

    # ── Response text (with left accent border) ──

    def _paint_response(self, p: QPainter, accent: QColor):
        if not self.response_text:
            return

        y_start = BAR_AREA_TOP + BAR_MAX_HEIGHT + 20
        if self.transcript_text:
            y_start += 22

        border_x = WAVEFORM_PADDING
        text_x = WAVEFORM_PADDING + 12
        avail_w = CARD_WIDTH - text_x - WAVEFORM_PADDING

        # Left accent border
        border_color = QColor(accent)
        border_color.setAlpha(180)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(border_color))

        font = QFont(FONT_BODY, 9)
        p.setFont(font)
        fm = QFontMetrics(font)

        text_rect = fm.boundingRect(
            QRect(0, 0, avail_w, 500),
            Qt.TextWordWrap,
            self.response_text
        )

        p.drawRoundedRect(
            QRectF(border_x, y_start - 2, 3, text_rect.height() + 6),
            1.5, 1.5
        )

        # Response text
        p.setPen(QPen(BRIGHT_TEXT))
        p.drawText(
            QRect(text_x, y_start, avail_w, text_rect.height() + 4),
            Qt.TextWordWrap,
            self.response_text
        )

    # ──────────────────────────────────────────────────────────
    #  Keyboard
    # ──────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.state_changed.emit("IDLE")
        else:
            super().keyPressEvent(event)

    # ──────────────────────────────────────────────────────────
    #  Dragging
    # ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = None
            event.accept()

    # ──────────────────────────────────────────────────────────
    #  Public convenience methods
    # ──────────────────────────────────────────────────────────

    def set_state(self, state: str):
        """Thread-safe state change."""
        self.state_changed.emit(state)

    def set_transcript(self, text: str):
        """Thread-safe transcript update."""
        self.transcript_updated.emit(text)

    def set_response(self, text: str):
        """Thread-safe response update."""
        self.response_updated.emit(text)

    def activate(self):
        """Show the HUD (convenience alias)."""
        if self.current_state == "IDLE":
            self.set_state("LISTENING")

    def hide_hud(self):
        """Hide the HUD (convenience alias)."""
        self.set_state("IDLE")


# ──────────────────────────────────────────────────────────────
#  Standalone demo
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    hud = KarenHUD()

    # Demo sequence
    def demo():
        # 1. Show LISTENING
        hud.state_changed.emit("LISTENING")

        # 2. Transcript appears
        QTimer.singleShot(1200, lambda: hud.transcript_updated.emit(
            "Karen, what broke last night?"
        ))

        # 3. Transition to THINKING
        QTimer.singleShot(3000, lambda: hud.state_changed.emit("THINKING"))

        # 4. Transition to SPEAKING with response
        def show_response():
            hud.state_changed.emit("SPEAKING")
            hud.response_updated.emit(
                "Three build failures — all the ingest worker. "
                "Fix branch is staged for review."
            )

        QTimer.singleShot(4500, show_response)

        # 5. Back to IDLE
        QTimer.singleShot(9000, lambda: hud.state_changed.emit("IDLE"))

        # 6. Second round — LISTENING only
        QTimer.singleShot(10500, lambda: hud.state_changed.emit("LISTENING"))
        QTimer.singleShot(12000, lambda: hud.transcript_updated.emit(
            "Open Brave browser"
        ))
        QTimer.singleShot(14000, lambda: hud.state_changed.emit("IDLE"))

    QTimer.singleShot(500, demo)

    sys.exit(app.exec())