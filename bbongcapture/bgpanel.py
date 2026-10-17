"""Popup panel for the Background tool."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QGridLayout,
                             QHBoxLayout, QInputDialog, QLabel, QPushButton, QSlider, QToolButton, QVBoxLayout)

from .background import GRADIENTS, RATIOS, BgSpec
from .settings import settings
from .theme import C, px

KINDS = [("none", "없음"), ("transparent", "투명"), ("gradient", "그라데이션"), ("solid", "단색"), ("image", "이미지"),
         ("wallpaper", "바탕화면")]


def _grad_css(stops, angle):
    s = ", ".join(f"stop:{p} {c}" for p, c in stops)
    return f"qlineargradient(x1:0, y1:0, x2:1, y2:1, {s})"


class BackgroundPanel(QFrame):
    changed = pyqtSignal(object)

    def __init__(self, spec: BgSpec, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("panel")
        self.spec = spec.clone()
        self._lock = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(px(16), px(14), px(16), px(16))
        lay.setSpacing(px(10))

        title = QLabel("<b>배경</b>")
        lay.addWidget(title)

        # kind chips
        row = QHBoxLayout()
        row.setSpacing(px(4))
        self.kind_group = QButtonGroup(self)
        self.kind_btns = {}
        for key, label in KINDS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setStyleSheet(f"QPushButton{{padding:{px(5)}px {px(8)}px;border-radius:{px(11)}px;background:{C['g_panel2']};border:1px solid {C['g_border']};}}"
                            f"QPushButton:hover{{background:{C['g_hover']};}}"
                            f"QPushButton:checked{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #4aa3ff,stop:1 #0a84ff);color:white;border:none;}}")
            self.kind_group.addButton(b)
            b.clicked.connect(lambda _, k=key: self._set("kind", k))
            row.addWidget(b)
            self.kind_btns[key] = b
        lay.addLayout(row)

        # gradients
        self.grad_box = QFrame()
        g = QGridLayout(self.grad_box)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(px(6))
        self.grad_group = QButtonGroup(self)
        self.grad_btns = []
        for i, (name, angle, stops) in enumerate(GRADIENTS):
            b = QToolButton()
            b.setCheckable(True)
            b.setToolTip(name)
            b.setFixedSize(px(50), px(34))
            b.setStyleSheet(f"QToolButton{{background:{_grad_css(stops, angle)};border-radius:{px(9)}px;border:2px solid transparent;}}"
                            f"QToolButton:checked{{border:2px solid {C['accent']};}}"
                            f"QToolButton:hover{{border:2px solid {C['text']};}}")
            self.grad_group.addButton(b)
            b.clicked.connect(lambda _, n=i: (self._set("gradient", n), self._set("kind", "gradient")))
            g.addWidget(b, i // 5, i % 5)
            self.grad_btns.append(b)
        lay.addWidget(self.grad_box)

        # solid / image
        row = QHBoxLayout()
        self.color_btn = QPushButton("단색 선택…")
        self.color_btn.clicked.connect(self._pick_color)
        self.image_btn = QPushButton("이미지 선택…")
        self.image_btn.clicked.connect(self._pick_image)
        row.addWidget(self.color_btn)
        row.addWidget(self.image_btn)
        lay.addLayout(row)

        # sliders
        def slider(label, lo, hi, key):
            r = QHBoxLayout()
            lab = QLabel(label)
            lab.setMinimumWidth(px(56))
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            v = QLabel("0")
            v.setMinimumWidth(px(28))
            s.valueChanged.connect(lambda val: (v.setText(str(val)), self._set(key, val)))
            r.addWidget(lab)
            r.addWidget(s)
            r.addWidget(v)
            lay.addLayout(r)
            return s, v

        self.pad_s, self.pad_v = slider("여백", 0, 240, "padding")
        self.rad_s, self.rad_v = slider("모서리", 0, 48, "radius")
        self.shb_s, self.shb_v = slider("그림자", 0, 100, "shadow_blur")

        row = QHBoxLayout()
        self.shadow_cb = QCheckBox("그림자")
        self.shadow_cb.toggled.connect(lambda v: self._set("shadow", v))
        self.balance_cb = QCheckBox("자동 균형")
        self.balance_cb.setToolTip("콘텐츠 주변 여백을 자동으로 맞춰 가운데 정렬합니다")
        self.balance_cb.toggled.connect(lambda v: self._set("balance", v))
        row.addWidget(self.shadow_cb)
        row.addWidget(self.balance_cb)
        row.addStretch()
        lay.addLayout(row)

        # alignment + ratio
        row = QHBoxLayout()
        self.align_lbl = QLabel("이미지 위치")
        self.align_lbl.setToolTip("캔버스 안에서 스크린샷을 어디에 둘지 정합니다 (비율을 지정했을 때 적용)")
        row.addWidget(self.align_lbl)
        ag = QGridLayout()
        ag.setSpacing(px(3))
        self.align_group = QButtonGroup(self)
        self.align_btns = {}
        for j in range(3):
            for i in range(3):
                b = QToolButton()
                b.setCheckable(True)
                b.setFixedSize(px(22), px(22))
                b.setToolTip(["위", "가운데", "아래"][j] + " · " + ["왼쪽", "가운데", "오른쪽"][i])
                b.setStyleSheet(f"QToolButton{{background:{C['g_panel2']};border:1px solid {C['g_border']};border-radius:{px(7)}px;}}"
                                f"QToolButton:hover{{border:1px solid {C['accent']};}}"
                                f"QToolButton:checked{{background:{C['accent']};border:1px solid {C['accent']};}}"
                                f"QToolButton:disabled{{background:{C['g_panel']};border:1px solid {C['g_border']};}}")
                self.align_group.addButton(b)
                b.clicked.connect(lambda _, a=(i / 2, j / 2): self._set("align", a))
                ag.addWidget(b, j, i)
                self.align_btns[(i / 2, j / 2)] = b
        row.addLayout(ag)
        row.addSpacing(px(14))
        row.addWidget(QLabel("비율"))
        self.ratio = QComboBox()
        self.ratio.addItems(list(RATIOS))
        self.ratio.currentTextChanged.connect(lambda t: self._set("ratio", t))
        row.addWidget(self.ratio)
        row.addStretch()
        lay.addLayout(row)
        self.align_hint = QLabel("비율을 자동 이외로 선택하면 이미지 위치를 정할 수 있어요")
        self.align_hint.setObjectName("muted")
        self.align_hint.setWordWrap(True)
        lay.addWidget(self.align_hint)

        # presets
        row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.setMinimumWidth(px(130))
        self.preset.activated.connect(self._load_preset)
        save = QPushButton("프리셋 저장")
        save.clicked.connect(self._save_preset)
        dele = QPushButton("삭제")
        dele.clicked.connect(self._del_preset)
        row.addWidget(self.preset, 1)
        row.addWidget(save)
        row.addWidget(dele)
        lay.addLayout(row)

        self.setFixedWidth(px(372))
        self._reload_presets()
        self.sync()

    # ------------------------------------------------------------------ painting (rounded translucent popup)
    def paintEvent(self, e):
        from .theme import paint_glass
        paint_glass(self, px(26), 236, C["mode"] == "dark")

    # ------------------------------------------------------------------ state
    def sync(self):
        self._lock = True
        s = self.spec
        for k, b in self.kind_btns.items():
            b.setChecked(k == s.kind)
        for i, b in enumerate(self.grad_btns):
            b.setChecked(s.kind == "gradient" and i == s.gradient)
        self.pad_s.setValue(s.padding)
        self.pad_v.setText(str(s.padding))
        self.rad_s.setValue(s.radius)
        self.rad_v.setText(str(s.radius))
        self.shb_s.setValue(s.shadow_blur)
        self.shb_v.setText(str(s.shadow_blur))
        self.shadow_cb.setChecked(s.shadow)
        self.balance_cb.setChecked(s.balance)
        b = self.align_btns.get(tuple(s.align))
        if b:
            b.setChecked(True)
        self.ratio.setCurrentText(s.ratio)
        has_ratio = s.ratio != "자동"          # alignment only matters when the canvas has spare room
        for b in self.align_btns.values():
            b.setEnabled(has_ratio)
        self.align_lbl.setEnabled(has_ratio)
        self.align_hint.setVisible(not has_ratio)
        self.adjustSize()
        from PyQt5.QtGui import QColor, QIcon, QPixmap
        pm = QPixmap(px(16), px(16))
        pm.fill(QColor(s.color))
        self.color_btn.setIcon(QIcon(pm))
        self._lock = False

    def _set(self, key, value):
        if self._lock:
            return
        setattr(self.spec, key, value)
        if key == "padding" and self.spec.kind == "none":
            self.spec.kind = "gradient"
        if key in ("padding", "radius", "shadow_blur", "shadow", "align", "ratio", "balance") and self.spec.kind == "none":
            self.spec.kind = "gradient"
        self.sync()
        self.changed.emit(self.spec.clone())

    def _pick_color(self):
        c = QColorDialog.getColor(parent=self)
        if c.isValid():
            self.spec.color = c.name()
            self._set("kind", "solid")

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "배경 이미지", "", "이미지 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self.spec.image = path
            self._set("kind", "image")

    # ------------------------------------------------------------------ presets
    def _reload_presets(self):
        self.preset.clear()
        self.preset.addItem("프리셋 선택…")
        for name in settings["bg_presets"]:
            self.preset.addItem(name)

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "프리셋 저장", "프리셋 이름")
        if ok and name.strip():
            settings["bg_presets"][name.strip()] = self.spec.to_dict()
            settings.save()
            self._reload_presets()
            self.preset.setCurrentText(name.strip())

    def _del_preset(self):
        name = self.preset.currentText()
        if name in settings["bg_presets"]:
            del settings["bg_presets"][name]
            settings.save()
            self._reload_presets()

    def _load_preset(self, i):
        name = self.preset.currentText()
        d = settings["bg_presets"].get(name)
        if d:
            self.spec = BgSpec.from_dict(d)
            self.sync()
            self.changed.emit(self.spec.clone())
