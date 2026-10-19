"""Offline first-use walkthrough. Actions operate the real analysis window."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout

STEPS = [
    ("Start with a side-camera video", "Crater follows the physical crater interface in side-view footage, including plume–surface experiments. It measures rim-to-rim width, vertical depth and cross-section area, not volume or a top-down crater count. Everything stays on your computer.<br><br>Try the bundled synthetic practice clip, or open your own video. The practice clip is an illustration, not experimental validation.", "Open practice video", "load_practice"),
    ("Set a real scale", "In the Calibration panel, enter the real width of the entire image and click <b>Use width</b>. For better calibration click <b>Measure…</b>, then two image points a known distance apart and enter that distance in mm.<br><br>The practice image is <b>64 mm wide</b> (640 px). Measure in the crater's optical plane. Until you confirm a scale, results use pixels and calibrated export is unavailable.", "Focus calibration", "focus_calibration"),
    ("Trace the physical crater interface", "The target can be a subsurface interface seen through the tank; do not automatically choose the brightest top boundary.<br><br>Click <b>Edit</b> on the left. Add points from flat ground on the left, down through the crater, and back onto flat ground on the right. Use several points along each flat wing and the curved basin. After three points the line is kept automatically; additional clicks refine it.<br><br>Drag points to move them; right-click a point to remove it. <b>Esc</b> finishes editing. The white line is the edge-refined result. Check it against the actual interface, especially near reflections. <b>Tools → Original threshold tuner</b> also lets you seed a line using the original sliders and mask.", "Start editing", "start_editing"),
    ("Read the measurements", "The inspector shows width, maximum vertical depth, section area and baseline tilt. The view below the video stretches the depth axis to make shallow craters readable; its dimension labels report the measured values.<br><br>Amber points are your guide. White is the tracked profile; the dashed baseline and rim ticks show what is measured. <b>Snap</b> refines within ±14 px. <b>Contrast</b> and <b>Median</b> are review aids only: exports and measurements always use the original frame.", "Finish editing", "escape"),
    ("Add a second keyframe", "Step forward with the arrow buttons or click the timeline. A <b>held</b> line carries the nearest keyframe forward; it has not been verified on this frame. Click <b>Edit</b> to adjust it or <b>Keep</b> if it is already right.<br><br>Between keyframes the guide is interpolated, then locally refined. One keyframe exports one frame; two or more export their sampled interval. Frames are numbered from zero.", "Forward 24 frames", "tutorial_step_forward"),
    ("Review weak tracking", "The timeline shows event activity, kept keyframes and tracking quality. Amber marks weak image support; <b>Next weak frame</b> jumps to a sampled frame needing review. Add keyframes where the line misses the interface.<br><br><b>Find event</b> is a navigation suggestion and can fail on lighting changes. Edge support and confidence rank frames for review; they are not error bars or proof that the physical interface is correct.", "Next weak frame", "next_weak_frame"),
    ("Save, export, and reopen", "Click <b>Save</b> to store keyframes, scale and snap setting in a session. Keep the original video: a session references it rather than copying it. Use <b>File → Open Session…</b> to reopen; moved videos can be located again.<br><br><b>Export CSV…</b> measures every sampled frame between your first and last keyframes, always including the keyframes. Enable <b>profiles</b> for profile points. Keep the companion <b>_meta.json</b> with the CSV: it records how the measurements were made. Validate against hand-labelled experimental frames before reporting research results.", "Save session", "save_session"),
]

REFERENCE = """
<h2>Crater: quick reference</h2>
<p>Offline, operator-guided analysis of side-view crater interfaces.</p>
<h3>Trace and measure</h3>
<p>Open video → confirm scale → Edit → click along the interface with flat wings on both sides → finish editing → add keyframes → review → Save → Export CSV.</p>
<p>D edits; click adds; drag moves; right-click deletes. Three points automatically keep a keyframe. S keeps a derived line; X clears the current keyframe; Undo reverses line edits. Escape stops editing or calibration.</p>
<h3>Navigate</h3>
<p>Left/Right: one frame. Shift+Left/Right: 24 frames. [ / ]: previous/next keyframe. N: next sampled weak frame. Space: play/pause at the video's recorded frame rate. Wheel: zoom video. Alt-drag: pan. F: fit. The timeline can be clicked or dragged; scroll it to zoom.</p>
<h3>Tools and original workflow</h3>
<p>E: edge snap within ±14 px of your guide. C: display contrast. T: seven-sample temporal median for visual review, which can blur evolving surfaces. Neither review aid changes analysis pixels. K: two-point scale. P: full-resolution overlay PNG. Tools → Original threshold tuner exposes threshold, smoothing, despeckle, independent left/right zones, surface boundary and scan direction, alongside the mask. Tools → Review Original Saved Profile reopens settings from older sessions. Inspect the candidate and use it as an editable keyframe.</p>
<h3>Interpretation and limits</h3>
<p>Rims are where the profile departs from the flat wings. Width is horizontal; depth is vertical below the rim baseline. Cross-section area is not volume. Refraction and lens distortion are not corrected. An annotation is not independent ground truth. A strong edge may still be the wrong interface.</p>
<p>Held and interpolated lines are derived from your keyframes. Confidence is a review indicator, not an uncertainty interval. Find event locates activity, not a guaranteed crater. A single keyframe exports that frame only.</p>
<h3>Sessions and exports</h3>
<p>Sessions are JSON files in ~/.crater_analysis/sessions/; File → Show Session Folder opens it. Videos stay at their original locations. CSV exports use mm and mm² only after scale confirmation and include source, distance to keyframe, edge support, confidence and notes. The companion _meta.json stores calibration, guides, app version and analysis settings.</p>
"""


class Tutorial(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.index = 0
        self.setWindowTitle("Crater · Built-in tutorial")
        self.resize(610, 470)
        self.setModal(False)
        layout = QVBoxLayout(self)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        self.heading.setStyleSheet("font-size: 20px; padding: 8px 0;")
        layout.addWidget(self.heading)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(False)
        layout.addWidget(self.body, 1)
        self.action = QPushButton()
        self.action.setObjectName("primary")
        self.action.clicked.connect(self.run_action)
        layout.addWidget(self.action)
        hint = QLabel("The tutorial stays open while you work. Move it aside or close it; reopen from Help at any time.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)
        nav = QHBoxLayout()
        self.back = QPushButton("Back")
        self.back.clicked.connect(lambda: self.go(-1))
        nav.addWidget(self.back)
        nav.addStretch()
        close = QPushButton("Close tutorial")
        close.clicked.connect(self.close)
        nav.addWidget(close)
        self.next = QPushButton("Next")
        self.next.clicked.connect(lambda: self.go(1))
        nav.addWidget(self.next)
        layout.addLayout(nav)
        self.refresh()

    def go(self, delta):
        self.index = min(len(STEPS) - 1, max(0, self.index + delta))
        self.refresh()

    def refresh(self):
        title, body, action, _ = STEPS[self.index]
        self.heading.setText(f"{self.index + 1} / {len(STEPS)}  ·  {title}")
        self.body.setHtml(body)
        self.action.setText(action)
        self.back.setEnabled(self.index > 0)
        self.next.setEnabled(self.index < len(STEPS) - 1)

    def run_action(self):
        if self.index and self.window.video is None:
            self.window.flash("Open a video or the practice clip first")
            return
        getattr(self.window, STEPS[self.index][3])()


def show_reference(window):
    dialog = QDialog(window)
    dialog.setWindowTitle("Crater · Offline help")
    dialog.resize(680, 560)
    layout = QVBoxLayout(dialog)
    browser = QTextBrowser()
    browser.setHtml(REFERENCE)
    layout.addWidget(browser)
    close = QPushButton("Close")
    close.clicked.connect(dialog.close)
    layout.addWidget(close)
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    dialog.show()
