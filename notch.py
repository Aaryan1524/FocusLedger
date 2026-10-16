"""Notch companion — FocusLedger's home on the Mac.

The panel is a single CAShapeLayer drawn in the classic dynamic-notch
silhouette: the top corners flare OUTWARD so the black surface flows into
the real notch with no visible seam, the bottom corners carry a deep
radius, and every state change is spring-animated (design inspired by the
open-source DynamicNotch project; implementation is original).

Collapsed, it hugs the physical notch with slim wings and a status dot.
Click it any time:
- On first launch (or via "⚙ Setup"), a native Onboarding Wizard verifies
  Ollama + Gemma, Screen Recording permission, and Voice Dictation.
- Each morning it asks your goals (with optional ⚡ Quick 1m test mode);
- Afterwards it shows live session status, flushes live checkpoints on
  "View report", generates full hybrid demo reports on "Demo day", or lets
  you reset with "New day" / close out with "End my day".

Run:            python notch.py
Onboarding:     python notch.py --onboarding
Quick test:     FL_DEV=1 python notch.py
Login launch:   python notch.py --install-login   (writes a LaunchAgent)
"""

import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date

import AppKit
import mss
import objc
import Quartz
from PyObjCTools import AppHelper

import focusledger as fl
import gemma

BASE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
DICTATE_APP = os.path.join(BASE, "Dictate.app")   # Swift speech-to-text helper
DICTATE_EXE = "Dictate.app/Contents/MacOS/dictate"
ONBOARDING_FLAG = os.path.join(BASE, ".onboarding_done")
SAMPLE_GOALS = "Ship FocusLedger onboarding; study calculus integrals; keep Slack under 20m"

# The window itself is a fixed, transparent stage; only the black shape
# inside it animates. That is what makes the motion buttery — we never
# resize the window, we spring the layer.
FRAME_W, FRAME_H = 760, 440

# Spring tuned to the "balanced" dynamic-notch feel: response ~0.47s,
# damping fraction 0.77.
SPRING_STIFFNESS = (2 * math.pi / 0.47) ** 2   # ≈ 179
SPRING_DAMPING = 2 * 0.77 * math.sqrt(SPRING_STIFFNESS)  # ≈ 21
SPRING_DURATION = 0.8

# Luxury Editorial Aesthetic (Te Vártá inspiration on pure pitch black background)
INK         = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.95, 0.94, 0.91, 1.0)  # Off-white / Cream (#F2EFE7)
MUTED       = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.64, 0.61, 0.56, 1.0)  # Warm Taupe / Sand (#A39C8F)
FAINT       = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.95, 0.94, 0.91, 0.40) # Muted Faint
CREAM_CTA   = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.90, 0.86, 1.0)  # Primary Off-White Pill (#ECE6DC)
CREAM_TEXT  = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.10, 0.09, 0.08, 1.0)  # Dark Charcoal Text (#1A1714)
GLASS_BG    = AppKit.NSColor.colorWithCalibratedWhite_alpha_(0.11, 1.0)                       # Translucent Glass Pill
ACTIVE_BG   = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.22, 0.19, 0.15, 1.0)  # Warm Highlight Pill
FIELD_BG    = AppKit.NSColor.colorWithCalibratedWhite_alpha_(0.07, 1.0)                       # Soft Frosted Field Fill
GREEN       = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.85, 0.76, 0.65, 1.0)  # Warm Almond Accent (#D8C3A5)
OK_COLOR    = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.58, 0.78, 0.62, 1.0)  # Soft Sage Green
WARN_COLOR  = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.82, 0.48, 0.42, 1.0)  # Terracotta Rust

_WEIGHTS = {
    "regular": AppKit.NSFontWeightRegular,
    "medium": AppKit.NSFontWeightMedium,
    "semibold": AppKit.NSFontWeightSemibold,
    "bold": AppKit.NSFontWeightBold,
}


def _serif(size, italic=False, weight="regular"):
    """Editorial serif font (Georgia / New York / Palatino) for luxury minimalist aesthetic."""
    font_name = "Georgia-Italic" if italic else ("Georgia-Bold" if weight == "bold" else "Georgia")
    f = AppKit.NSFont.fontWithName_size_(font_name, size)
    if f is None:
        f = AppKit.NSFont.systemFontOfSize_weight_(size, _WEIGHTS.get(weight, AppKit.NSFontWeightRegular))
    return f


def _font(size, weight="regular", rounded=False, mono=False):
    """System font for clean monospaced digits and metadata captions."""
    w = _WEIGHTS[weight]
    f = (AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(size, w)
         if mono else AppKit.NSFont.systemFontOfSize_weight_(size, w))
    return f


def _label(text, frame, font, color):
    lb = AppKit.NSTextField.alloc().initWithFrame_(frame)
    lb.setStringValue_(text)
    lb.setBezeled_(False); lb.setDrawsBackground_(False)
    lb.setEditable_(False); lb.setSelectable_(False)
    lb.setFont_(font)
    lb.setTextColor_(color)
    return lb


def check_system_readiness():
    """Fast non-blocking readiness check for Onboarding Wizard."""
    # 1. Local AI (Ollama + Gemma)
    ai = gemma.check_ollama(timeout=1.2)
    ai_ok = ai["server_ok"] and ai["model_ok"]
    ai_status = ai["detail"]

    # 2. Screen Capture permission
    screen_ok = False
    screen_status = "Needs Screen Recording permission"
    try:
        preflight_ok = True
        if hasattr(Quartz, "CGPreflightScreenCaptureAccess"):
            preflight_ok = bool(Quartz.CGPreflightScreenCaptureAccess())
        with mss.MSS() as sct:
            img = sct.grab(sct.monitors[1])
        px = img.rgb
        distinct = len(set(px[i:i + 3] for i in range(0, min(len(px), 150000), 3)))
        if preflight_ok and distinct >= 5:
            screen_ok = True
            screen_status = f"Granted ({img.size.width}×{img.size.height} Vision OCR)"
    except Exception:
        screen_ok = False

    # 3. On-Device Voice helper (Dictate.app)
    exe = os.path.join(DICTATE_APP, "Contents", "MacOS", "dictate")
    voice_ok = os.path.exists(exe)
    voice_status = "On-device Speech.framework ready" if voice_ok else "Helper not compiled yet"

    return {
        "ai_ok": ai_ok,
        "ai_server_ok": ai["server_ok"],
        "ai_status": ai_status,
        "screen_ok": screen_ok,
        "screen_status": screen_status,
        "voice_ok": voice_ok,
        "voice_status": voice_status,
        "all_critical_ok": ai_ok and screen_ok,
    }


def notch_path(x0, x1, ytop, ybot, tr, br):
    """The notch silhouette (bottom-left coords): top corners flare outward
    (concave, so the shape melts into the menu bar), bottom corners are
    convex with a deep radius."""
    p = Quartz.CGPathCreateMutable()
    Quartz.CGPathMoveToPoint(p, None, x0, ytop)
    Quartz.CGPathAddQuadCurveToPoint(p, None, x0 + tr, ytop, x0 + tr, ytop - tr)
    Quartz.CGPathAddLineToPoint(p, None, x0 + tr, ybot + br)
    Quartz.CGPathAddQuadCurveToPoint(p, None, x0 + tr, ybot, x0 + tr + br, ybot)
    Quartz.CGPathAddLineToPoint(p, None, x1 - tr - br, ybot)
    Quartz.CGPathAddQuadCurveToPoint(p, None, x1 - tr, ybot, x1 - tr, ybot + br)
    Quartz.CGPathAddLineToPoint(p, None, x1 - tr, ytop - tr)
    Quartz.CGPathAddQuadCurveToPoint(p, None, x1 - tr, ytop, x1, ytop)
    Quartz.CGPathCloseSubpath(p)
    return p


class NotchPanel(AppKit.NSPanel):
    def canBecomeKeyWindow(self):
        return True


class RootView(AppKit.NSView):
    """Transparent stage; only the current shape rect accepts clicks so the
    rest of the window never steals mouse events from apps beneath it."""
    def initWithFrame_(self, frame):
        self = objc.super(RootView, self).initWithFrame_(frame)
        if self is not None:
            self.hotRect = AppKit.NSMakeRect(0, 0, 0, 0)
            self.onClick = None
        return self

    def acceptsFirstMouse_(self, event):
        return True  # respond to the first click even when the app is inactive

    def hitTest_(self, point):
        p = self.convertPoint_fromView_(point, None) if self.superview() is None else point
        if AppKit.NSPointInRect(p, self.hotRect):
            return objc.super(RootView, self).hitTest_(point)
        return None

    def mouseDown_(self, event):
        if self.onClick is not None:
            self.onClick()


class App(AppKit.NSObject):
    def applicationDidFinishLaunching_(self, note):
        self.tracker = None
        self.status = {"line": "idle — waiting for keyboard/mouse activity", "session": "session ready"}
        self.expanded = False
        self.day_done = False
        self.quick_mode = bool(os.environ.get("FL_DEV"))
        self.flush_event = threading.Event()
        self.readiness = check_system_readiness()

        force_onboarding = ("--onboarding" in sys.argv) or bool(os.environ.get("FL_ONBOARDING"))
        first_run = not os.path.exists(ONBOARDING_FLAG)
        self.onboarding_mode = force_onboarding or first_run or (not self.readiness["all_critical_ok"])

        screen = AppKit.NSScreen.screens()[0]
        f, v = screen.frame(), screen.visibleFrame()
        self.mb = int((f.origin.y + f.size.height) - (v.origin.y + v.size.height))

        # Real notch width when the API is available; sane fallback otherwise.
        self.notch_w = 200
        try:
            tl, tr = screen.auxiliaryTopLeftArea(), screen.auxiliaryTopRightArea()
            if tl is not None and tr is not None:
                self.notch_w = int(f.size.width - tl.size.width - tr.size.width)
        except AttributeError:
            pass

        rect = AppKit.NSMakeRect(0, 0, FRAME_W, FRAME_H)
        style = (AppKit.NSWindowStyleMaskBorderless
                 | AppKit.NSWindowStyleMaskNonactivatingPanel)  # clicks land without app activation
        self.panel = NotchPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False)
        self.panel.setLevel_(AppKit.NSPopUpMenuWindowLevel)  # reliably above the menu bar
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        self.panel.setHasShadow_(False)  # the shape layer carries its own shadow
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary)

        x = f.origin.x + (f.size.width - FRAME_W) / 2.0
        y = f.origin.y + f.size.height - FRAME_H
        self.panel.setFrame_display_(AppKit.NSMakeRect(x, y, FRAME_W, FRAME_H), False)

        self.root = RootView.alloc().initWithFrame_(rect)
        self.root.setWantsLayer_(True)
        self.panel.setContentView_(self.root)

        self.shape = Quartz.CAShapeLayer.layer()
        self.shape.setFillColor_(AppKit.NSColor.blackColor().CGColor())
        self.shape.setShadowColor_(AppKit.NSColor.blackColor().CGColor())
        self.shape.setShadowOpacity_(0.55)
        self.shape.setShadowRadius_(14.0)
        self.shape.setShadowOffset_(AppKit.NSMakeSize(0, -5))
        self.root.layer().addSublayer_(self.shape)

        # Live-activity wings: status dot on the left, session timer on the right.
        self.dot = Quartz.CALayer.layer()
        self.dot.setBackgroundColor_(MUTED.CGColor())
        self.dot.setCornerRadius_(3.5)
        self.root.layer().addSublayer_(self.dot)

        self.timeLabel = _label("", AppKit.NSMakeRect(0, 0, 10, 10),
                                _font(11.5, "semibold", rounded=True, mono=True), GREEN)
        self.timeLabel.setAlignment_(AppKit.NSTextAlignmentRight)
        self.root.addSubview_(self.timeLabel)
        self.session_start = None

        # Content sits inside the expanded shape, below the menu-bar band.
        er = self.shape_rect(True)
        self.content = AppKit.NSView.alloc().initWithFrame_(er)
        self.content.setWantsLayer_(True)
        self.content.setAlphaValue_(0.0)
        self.root.addSubview_(self.content)

        # Clicking the notch expands it; clicking outside collapses it.
        self.root.onClick = self._notchClicked
        self.globalMonitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            AppKit.NSEventMaskLeftMouseDown, self._outsideClick)

        self.apply_state(animate=False)
        self.panel.orderFrontRegardless()

        self.goals = fl.load_todays_goals()
        if self.onboarding_mode:
            self.setExpanded_(True)
        elif self.goals:
            self.startTracker()
        else:
            self.setExpanded_(True)

        AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "tick:", None, True)

    # ---------- geometry & animation ----------

    @objc.python_method
    def shape_rect(self, expanded):
        """Shape bounds in window coords (bottom-left origin, top edge = FRAME_H)."""
        if expanded:
            if getattr(self, "onboarding_mode", False):
                w, h = 430, self.mb + 232
            else:
                w, h = 430, self.mb + 190
        else:
            w, h = self.notch_w + 150, self.mb + 12
        x0 = (FRAME_W - w) / 2.0
        return AppKit.NSMakeRect(x0, FRAME_H - h, w, h)

    @objc.python_method
    def _spring(self, key, from_v, to_v):
        a = Quartz.CASpringAnimation.animationWithKeyPath_(key)
        a.setMass_(1.0)
        a.setStiffness_(SPRING_STIFFNESS)
        a.setDamping_(SPRING_DAMPING)
        a.setDuration_(SPRING_DURATION)
        a.setFromValue_(from_v)
        a.setToValue_(to_v)
        return a

    @objc.python_method
    def apply_state(self, animate=True):
        r = self.shape_rect(self.expanded)
        tr, br = (12.0, 26.0) if self.expanded else (9.0, 12.0)
        new_path = notch_path(r.origin.x, r.origin.x + r.size.width,
                              FRAME_H, r.origin.y, tr, br)
        old_path = self.shape.path()
        self.shape.setPath_(new_path)
        if animate and old_path is not None:
            self.shape.addAnimation_forKey_(
                self._spring("path", old_path, new_path), "path")

        # Wing content: dot on the left wing, timer on the right — collapsed only.
        dr = self.shape_rect(False)
        wing = (dr.size.width - self.notch_w) / 2.0
        band_mid = FRAME_H - self.mb / 2.0
        dot_frame = AppKit.NSMakeRect(dr.origin.x + wing / 2.0 - 3.5, band_mid - 3.5, 7, 7)
        Quartz.CATransaction.begin()
        Quartz.CATransaction.setDisableActions_(True)
        self.dot.setFrame_(dot_frame)
        Quartz.CATransaction.commit()
        self.dot.setOpacity_(0.0 if self.expanded else 1.0)

        notch_right = dr.origin.x + dr.size.width - wing
        self.timeLabel.setFrame_(AppKit.NSMakeRect(
            notch_right + 4, band_mid - 8, wing - 20, 16))
        self.timeLabel.setAlphaValue_(0.0 if self.expanded else 1.0)

        self.root.hotRect = r
        self.content.setFrame_(self.shape_rect(True))
        if self.expanded:
            self.rebuild()
            if animate:
                self.content.setAlphaValue_(0.0)
                AppKit.NSAnimationContext.runAnimationGroup_completionHandler_(
                    lambda ctx: (ctx.setDuration_(0.32),
                                 self.content.animator().setAlphaValue_(1.0)), None)
            else:
                self.content.setAlphaValue_(1.0)
        else:
            self.content.setAlphaValue_(0.0)

    def setExpanded_(self, on):
        self.expanded = bool(on)
        if not self.expanded and getattr(self, "dictating", False):
            self._stop_dictation()  # never keep the mic open behind a collapsed panel
        self.apply_state(animate=True)

    @objc.python_method
    def _notchClicked(self):
        if not self.expanded:
            self.setExpanded_(True)

    @objc.python_method
    def _outsideClick(self, event):
        if self.expanded:
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                lambda: self.setExpanded_(False))

    # ---------- content states ----------

    def rebuild(self):
        for v in list(self.content.subviews()):
            v.removeFromSuperview()

        H = self.content.frame().size.height
        W = self.content.frame().size.width
        top = H - self.mb - 8   # stay clear of the physical notch band
        pad = 20

        # Header row: Centered FocusLedger title (18pt serif bold)
        title = _label("FocusLedger", AppKit.NSMakeRect(pad, top - 26, W - 2 * pad, 24),
                       _serif(18, weight="bold"), INK)
        title.setAlignment_(AppKit.NSTextAlignmentCenter)
        self.content.addSubview_(title)

        # Status dot far left & mode/privacy badge far right
        dot_col = OK_COLOR if self.tracker is not None else GREEN
        self.content.addSubview_(_label("●", AppKit.NSMakeRect(pad, top - 22, 14, 16),
                                        _font(9, "regular"), dot_col))
        badge_str = "⚡ QUICK 1M" if self.quick_mode else "100% LOCAL"
        tag = _label(badge_str, AppKit.NSMakeRect(W - pad - 95, top - 22, 95, 14),
                     _font(9, "medium"), GREEN if self.quick_mode else FAINT)
        tag.setAlignment_(AppKit.NSTextAlignmentRight)
        self.content.addSubview_(tag)

        # STATE 0: Native First-Run Onboarding & System Readiness Wizard
        if getattr(self, "onboarding_mode", False):
            r = self.readiness
            sub = _label("Welcome — verify your 100% on-device setup:",
                         AppKit.NSMakeRect(pad, top - 50, W - 2 * pad, 16),
                         _serif(12.5, italic=True), MUTED)
            self.content.addSubview_(sub)

            rows = [
                ("1. Local AI (Gemma 3)", r["ai_status"], r["ai_ok"],
                 None if r["ai_ok"] else ("Start Ollama", "fixOllama:")),
                ("2. Screen Capture & OCR", r["screen_status"], r["screen_ok"],
                 None if r["screen_ok"] else ("Grant Access", "openScreenPrefs:")),
                ("3. On-Device Voice", r["voice_status"], r["voice_ok"],
                 ("Ready ✓", None) if r["voice_ok"] else ("Build Helper", "buildVoice:")),
            ]
            y_cursor = top - 84
            for title_txt, detail_txt, ok_flag, btn_spec in rows:
                icon = "✓" if ok_flag else "○"
                ic_col = OK_COLOR if ok_flag else WARN_COLOR
                self.content.addSubview_(_label(icon, AppKit.NSMakeRect(pad, y_cursor, 16, 18),
                                                _font(12, "bold"), ic_col))
                self.content.addSubview_(_label(title_txt, AppKit.NSMakeRect(pad + 18, y_cursor + 2, 185, 16),
                                                _serif(12.5, weight="bold"), INK))
                det = _label(detail_txt, AppKit.NSMakeRect(pad + 18, y_cursor - 12, 260, 14),
                             _font(10.5, "regular"), MUTED)
                det.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
                self.content.addSubview_(det)

                if btn_spec is not None and btn_spec[1] is not None:
                    b = self._pill(btn_spec[0], btn_spec[1], ACTIVE_BG,
                                   AppKit.NSMakeRect(W - pad - 96, y_cursor - 6, 96, 22), text_color=INK)
                    self.content.addSubview_(b)
                else:
                    ok_pill = _label("READY", AppKit.NSMakeRect(W - pad - 60, y_cursor - 2, 60, 14),
                                     _font(9.5, "semibold"), OK_COLOR)
                    ok_pill.setAlignment_(AppKit.NSTextAlignmentRight)
                    self.content.addSubview_(ok_pill)
                y_cursor -= 38

            # Bottom Onboarding Controls
            self.content.addSubview_(self._pill("↻ Re-check", "recheckOnboarding:", GLASS_BG,
                                                AppKit.NSMakeRect(pad, 14, 96, 26), text_color=INK))
            self.content.addSubview_(self._pill("Preview demo", "demoReport:", GLASS_BG,
                                                AppKit.NSMakeRect(pad + 104, 14, 104, 26), text_color=INK))
            self.content.addSubview_(self._pill("Continue →", "finishOnboarding:", CREAM_CTA,
                                                AppKit.NSMakeRect(W - pad - 114, 14, 114, 26), text_color=CREAM_TEXT))
            return

        # STATE 1: Morning Goal Setup
        if self.tracker is None and self.goals is None and not self.day_done:
            self.content.addSubview_(_label("What are your goals today?",
                                            AppKit.NSMakeRect(pad, top - 54, W - 2 * pad - 80, 20),
                                            _serif(15, italic=False, weight="regular"), INK))
            self.content.addSubview_(self._pill("✨ Sample", "fillSampleGoals:", GLASS_BG,
                                                AppKit.NSMakeRect(W - pad - 74, top - 54, 74, 20), text_color=MUTED))
            self.content.addSubview_(_label("Say them or type them. Specific beats noble.",
                                            AppKit.NSMakeRect(pad, top - 73, W - 2 * pad, 14),
                                            _serif(11, italic=True), MUTED))
            self.field = AppKit.NSTextField.alloc().initWithFrame_(
                AppKit.NSMakeRect(pad, top - 108, W - 2 * pad, 28))
            self.field.setFont_(_font(12, "regular"))
            self.field.setTextColor_(INK)
            self.field.setBezeled_(False)
            self.field.setWantsLayer_(True)
            self.field.layer().setBackgroundColor_(FIELD_BG.CGColor())
            self.field.layer().setCornerRadius_(8.0)
            self.field.setFocusRingType_(AppKit.NSFocusRingTypeNone)
            self.field.setBackgroundColor_(FIELD_BG)
            self.field.setDrawsBackground_(True)
            self.field.setPlaceholderString_("Ship demo · study calc · keep Slack short")
            self.field.setTarget_(self); self.field.setAction_("startDay:")
            self.content.addSubview_(self.field)

            self.micBtn = self._pill(self._mic_label(), "speakGoals:", GLASS_BG,
                                     AppKit.NSMakeRect(pad, 14, 114, 26), text_color=INK)
            self.content.addSubview_(self.micBtn)

            mode_label = "⚡ Quick 1m" if self.quick_mode else "⏱ 30m std"
            mode_bg = ACTIVE_BG if self.quick_mode else GLASS_BG
            self.content.addSubview_(self._pill(mode_label, "toggleMode:", mode_bg,
                                                AppKit.NSMakeRect(pad + 122, 14, 96, 26),
                                                text_color=GREEN if self.quick_mode else MUTED))
            self.content.addSubview_(self._pill("⚙ Setup", "openOnboarding:", GLASS_BG,
                                                AppKit.NSMakeRect(pad + 226, 14, 66, 26), text_color=MUTED))
            self.content.addSubview_(self._pill("Start day", "startDay:", CREAM_CTA,
                                                AppKit.NSMakeRect(W - pad - 90, 14, 90, 26), text_color=CREAM_TEXT))
            self.panel.makeKeyAndOrderFront_(None)
            AppKit.NSApp.activateIgnoringOtherApps_(True)
            self.panel.makeFirstResponder_(self.field)

        # STATE 2: Active Session Tracking
        elif self.tracker is not None:
            self.sessLabel = _label(self.status["session"],
                                    AppKit.NSMakeRect(pad, top - 54, W - 2 * pad, 20),
                                    _serif(15, italic=False, weight="bold"), INK)
            self.lineLabel = _label(self.status["line"],
                                    AppKit.NSMakeRect(pad, top - 74, W - 2 * pad, 15),
                                    _font(11, "regular"), MUTED)
            self.lineLabel.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
            self.content.addSubview_(self.sessLabel)
            self.content.addSubview_(self.lineLabel)
            goals = _label("Goals · " + (self.goals or ""),
                           AppKit.NSMakeRect(pad, top - 95, W - 2 * pad, 15),
                           _serif(11, italic=True), FAINT)
            goals.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
            self.content.addSubview_(goals)

            self.content.addSubview_(self._pill("View report", "viewReport:", GLASS_BG,
                                                AppKit.NSMakeRect(pad, 14, 96, 26), text_color=INK))
            self.content.addSubview_(self._pill("Demo day", "demoReport:", GLASS_BG,
                                                AppKit.NSMakeRect(pad + 104, 14, 92, 26), text_color=INK))
            self.content.addSubview_(self._pill("New day", "resetDay:", GLASS_BG,
                                                AppKit.NSMakeRect(pad + 204, 14, 84, 26), text_color=MUTED))
            self.content.addSubview_(self._pill("End my day", "endDay:", CREAM_CTA,
                                                AppKit.NSMakeRect(W - pad - 94, 14, 94, 26), text_color=CREAM_TEXT))

        # STATE 3: Day Closed / Idle
        else:
            msg = "Day closed — report is open in your browser." if self.day_done else "Not tracking."
            self.content.addSubview_(_label(msg, AppKit.NSMakeRect(pad, top - 56, W - 2 * pad, 20),
                                            _serif(14, italic=False, weight="regular"), INK))
            sub = _label("Start a New day anytime to test again, or explore the full Demo day report.",
                         AppKit.NSMakeRect(pad, top - 78, W - 2 * pad, 15),
                         _serif(11, italic=True), MUTED)
            self.content.addSubview_(sub)

            self.content.addSubview_(self._pill("View report", "viewReport:", GLASS_BG,
                                                AppKit.NSMakeRect(pad, 14, 96, 26), text_color=INK))
            self.content.addSubview_(self._pill("Demo day", "demoReport:", GLASS_BG,
                                                AppKit.NSMakeRect(pad + 104, 14, 92, 26), text_color=INK))
            self.content.addSubview_(self._pill("New day", "resetDay:", CREAM_CTA,
                                                AppKit.NSMakeRect(pad + 204, 14, 96, 26), text_color=CREAM_TEXT))
            q = self._pill("Quit", None, GLASS_BG,
                           AppKit.NSMakeRect(W - pad - 82, 14, 82, 26), text_color=INK)
            q.setTarget_(AppKit.NSApp); q.setAction_("terminate:")
            self.content.addSubview_(q)

    @objc.python_method
    def _pill(self, title, action, bg, frame, text_color=None):
        """Rounded pill button: borderless, layer-backed capsule with serif/sans typography."""
        if text_color is None:
            text_color = CREAM_TEXT if bg == CREAM_CTA else INK
        btn = AppKit.NSButton.alloc().initWithFrame_(frame)
        btn.setBordered_(False)
        btn.setWantsLayer_(True)
        btn.layer().setBackgroundColor_(bg.CGColor())
        btn.layer().setCornerRadius_(frame.size.height / 2.0)
        font = _serif(12, weight="bold") if bg == CREAM_CTA else _font(11.0, "medium")
        attrs = {
            AppKit.NSFontAttributeName: font,
            AppKit.NSForegroundColorAttributeName: text_color,
        }
        btn.setAttributedTitle_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(title, attrs))
        if action:
            btn.setTarget_(self); btn.setAction_(action)
        return btn

    @objc.python_method
    def _pill_title(self, btn, title):
        """Retitle an existing pill."""
        attrs = {
            AppKit.NSFontAttributeName: _font(11.0, "medium"),
            AppKit.NSForegroundColorAttributeName: INK,
        }
        btn.setAttributedTitle_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(title, attrs))

    # ---------- onboarding & mode actions ----------

    def openOnboarding_(self, sender):
        self.readiness = check_system_readiness()
        self.onboarding_mode = True
        self.apply_state(animate=True)

    def recheckOnboarding_(self, sender):
        self.readiness = check_system_readiness()
        self.rebuild()

    def finishOnboarding_(self, sender):
        try:
            with open(ONBOARDING_FLAG, "w") as f:
                f.write(date.today().isoformat() + "\n")
        except OSError:
            pass
        self.onboarding_mode = False
        if self.goals and self.tracker is None and not self.day_done:
            self.startTracker()
        self.apply_state(animate=True)

    def fixOllama_(self, sender):
        def _bg():
            try:
                subprocess.Popen(["ollama", "serve"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(2.0)
            except OSError:
                pass
            self.readiness = check_system_readiness()
            self._on_main(self.rebuild)
        threading.Thread(target=_bg, daemon=True).start()

    def openScreenPrefs_(self, sender):
        try:
            if hasattr(Quartz, "CGRequestScreenCaptureAccess"):
                Quartz.CGRequestScreenCaptureAccess()
        except Exception:
            pass
        subprocess.run([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
        ], check=False)

    def buildVoice_(self, sender):
        def _bg():
            subprocess.run(["bash", os.path.join(BASE, "build_dictate.sh")], cwd=BASE, check=False)
            self.readiness = check_system_readiness()
            self._on_main(self.rebuild)
        threading.Thread(target=_bg, daemon=True).start()

    def toggleMode_(self, sender):
        saved_text = ""
        if getattr(self, "field", None) is not None:
            saved_text = self.field.stringValue()
        self.quick_mode = not self.quick_mode
        self.rebuild()
        if saved_text and getattr(self, "field", None) is not None:
            self.field.setStringValue_(saved_text)

    def fillSampleGoals_(self, sender):
        if getattr(self, "field", None) is not None:
            self.field.setStringValue_(SAMPLE_GOALS)

    # ---------- voice goals ----------

    LISTEN_TIMEOUT = 45      # generous: the helper caps itself well before this

    @objc.python_method
    def _mic_label(self):
        return "◉  Listening…" if getattr(self, "dictating", False) else "🎙  Speak goals"

    def speakGoals_(self, sender):
        if getattr(self, "dictating", False):
            self._stop_dictation()
            return
        if not os.path.exists(DICTATE_APP):
            self.field.setStringValue_("")
            self.field.setPlaceholderString_("helper not built — run ./build_dictate.sh")
            return
        self.dictating = True
        self._pill_title(self.micBtn, self._mic_label())
        threading.Thread(target=self._runDictation, daemon=True).start()

    @objc.python_method
    def _runDictation(self):
        """Launch the helper and stream its partial transcripts into the field."""
        tmp = tempfile.mkdtemp(prefix="fl-dictate-")
        out = os.path.join(tmp, "transcript.txt")
        done = out + ".done"
        try:
            subprocess.run(["open", "-n", DICTATE_APP, "--args", "--out", out],
                           check=True, cwd=BASE)
        except (OSError, subprocess.CalledProcessError) as e:
            shutil.rmtree(tmp, ignore_errors=True)
            self._on_main(self._end_dictation, f"could not start helper ({e})")
            return

        last = ""
        deadline = time.time() + self.LISTEN_TIMEOUT
        while time.time() < deadline and self.dictating:
            if os.path.exists(out):
                try:
                    cur = open(out).read().strip()
                except OSError:
                    cur = last
                if cur != last:
                    last = cur
                    if not cur.startswith("ERR:"):
                        self._on_main(self._apply_transcript, cur)
            if os.path.exists(done):
                break
            time.sleep(0.1)

        shutil.rmtree(tmp, ignore_errors=True)
        if last.startswith("ERR:"):
            self._on_main(self._end_dictation, last[4:].strip())
        else:
            self._on_main(self._end_dictation,
                          None if last else "didn't catch that — try again")

    @objc.python_method
    def _on_main(self, fn, *args):
        """Helper callbacks arrive on a reader thread; AppKit must be touched on main."""
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: fn(*args))

    @objc.python_method
    def _apply_transcript(self, text):
        f = getattr(self, "field", None)
        if f is not None and f.superview() is not None:
            f.setStringValue_(text)

    @objc.python_method
    def _end_dictation(self, error):
        self.dictating = False
        btn = getattr(self, "micBtn", None)
        if btn is not None and btn.superview() is not None:
            self._pill_title(btn, self._mic_label())
        f = getattr(self, "field", None)
        if error and f is not None and f.superview() is not None and not f.stringValue().strip():
            f.setPlaceholderString_(error)

    @objc.python_method
    def _stop_dictation(self):
        self.dictating = False
        try:
            subprocess.run(["pkill", "-f", DICTATE_EXE], check=False)
        except OSError:
            pass
        self._end_dictation(None)

    # ---------- session lifecycle & reports ----------

    def startDay_(self, sender):
        goals = self.field.stringValue().strip()
        if not goals:
            self.field.setPlaceholderString_("Please enter or speak your goals first (or click ✨ Sample)")
            return
        self.goals = goals
        self.day_done = False
        fl.append_ledger({"type": "goals", "date": date.today().isoformat(), "goals": goals})
        self.startTracker()
        self.setExpanded_(False)

    def startTracker(self):
        env = os.environ.copy()
        if self.quick_mode:
            env["FL_DEV"] = "1"
        else:
            env.pop("FL_DEV", None)
        self.tracker = subprocess.Popen(
            [PYTHON, "-u", os.path.join(BASE, "focusledger.py")],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=BASE, env=env)
        threading.Thread(target=self._reader, daemon=True).start()
        self.status["session"] = "tracking (⚡ 1m checkpoints)" if self.quick_mode else "tracking"
        self.dot.setBackgroundColor_(GREEN.CGColor())

    def _reader(self):
        from datetime import datetime
        proc = self.tracker
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            if line.startswith("▶"):
                self.status["session"] = line
                self.session_start = datetime.now()
            elif line.startswith("■"):
                self.status["session"] = line
                self.session_start = None
            elif line.startswith("✓ checkpoint flushed"):
                self.flush_event.set()
            elif line.startswith(("👁", "📒", "🧠", "⛔", "🔎")):
                self.status["line"] = line

    def viewReport_(self, sender):
        """Flush any active buffer via SIGUSR1, then render and open today's report."""
        ledger = os.path.join(BASE, "ledger.jsonl")
        if not os.path.exists(ledger) and self.tracker is None:
            self.status["line"] = "no ledger yet — click 'Demo day' or start your day first"
            self.rebuild()
            return
        self.status["line"] = "🧠 judging live activity & generating report with Gemma…"
        self.rebuild()
        threading.Thread(target=self._renderReport, daemon=True).start()

    def _renderReport(self):
        if self.tracker is not None and self.tracker.poll() is None:
            self.flush_event.clear()
            try:
                self.tracker.send_signal(signal.SIGUSR1)
                self.flush_event.wait(timeout=90.0)
            except Exception:
                pass
        subprocess.run([PYTHON, os.path.join(BASE, "report.py"),
                        os.path.join(BASE, "ledger.jsonl"), "--open"], cwd=BASE)
        self.status["line"] = "✓ report opened in your browser"
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(self.rebuild)

    def demoReport_(self, sender):
        """Build a full-day demo report (combining real session if present + seeded sessions)."""
        self.status["line"] = "🧠 synthesizing full-day demo report with Gemma…"
        if not self.onboarding_mode:
            self.rebuild()
        threading.Thread(target=self._renderDemoReport, daemon=True).start()

    def _renderDemoReport(self):
        real_ledger = os.path.join(BASE, "ledger.jsonl")
        demo_ledger = os.path.join(BASE, "ledger.demo.jsonl")
        demo_out = os.path.join(BASE, "report.demo.html")

        if self.tracker is not None and self.tracker.poll() is None:
            self.flush_event.clear()
            try:
                self.tracker.send_signal(signal.SIGUSR1)
                self.flush_event.wait(timeout=60.0)
            except Exception:
                pass

        if os.path.exists(real_ledger):
            subprocess.run([PYTHON, os.path.join(BASE, "seed.py"),
                            "--base", real_ledger, "--out", demo_ledger], cwd=BASE)
        else:
            subprocess.run([PYTHON, os.path.join(BASE, "seed.py"),
                            "--out", demo_ledger], cwd=BASE)

        subprocess.run([PYTHON, os.path.join(BASE, "report.py"),
                        demo_ledger, "--out", demo_out, "--open"], cwd=BASE)
        self.status["line"] = "✓ demo report opened in your browser"
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(self.rebuild)

    def resetDay_(self, sender):
        """Stop tracking, archive today's ledger, and return to the morning goal prompt."""
        proc, self.tracker = self.tracker, None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        fl.reset_todays_ledger()
        self.goals = None
        self.day_done = False
        self.session_start = None
        self.status = {"line": "idle — waiting for keyboard/mouse activity", "session": "session ready"}
        self.dot.setBackgroundColor_(MUTED.CGColor())
        self.apply_state(animate=True)

    def endDay_(self, sender):
        self.status["session"] = "closing day…"
        self.status["line"] = "flushing final checkpoint (Gemma is judging)"
        self.rebuild()
        threading.Thread(target=self._closeAndReport, daemon=True).start()

    def _closeAndReport(self):
        proc, self.tracker = self.tracker, None
        if proc is not None:
            try:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=180)
            except Exception:
                proc.kill()
        self.day_done = True
        self.session_start = None
        self.dot.setBackgroundColor_(MUTED.CGColor())
        subprocess.run([PYTHON, os.path.join(BASE, "report.py"),
                        os.path.join(BASE, "ledger.jsonl"), "--open"], cwd=BASE)
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(self.rebuild)

    def tick_(self, timer):
        from datetime import datetime
        if not self.expanded:
            if self.session_start is not None:
                mins = int((datetime.now() - self.session_start).total_seconds() // 60)
                self.timeLabel.setStringValue_(f"{mins // 60}:{mins % 60:02d}")
                self.timeLabel.setTextColor_(GREEN)
            else:
                self.timeLabel.setStringValue_("–" if self.tracker else "")
                self.timeLabel.setTextColor_(FAINT)
        elif self.tracker is not None and not self.onboarding_mode:
            if getattr(self, "sessLabel", None):
                self.sessLabel.setStringValue_(self.status["session"])
            if getattr(self, "lineLabel", None):
                self.lineLabel.setStringValue_(self.status["line"])


PLIST = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.focusledger.notch</string>
  <key>ProgramArguments</key>
  <array><string>{PYTHON}</string><string>{os.path.join(BASE, "notch.py")}</string></array>
  <key>RunAtLoad</key><true/>
  <key>WorkingDirectory</key><string>{BASE}</string>
</dict></plist>
"""


def install_login():
    path = os.path.expanduser("~/Library/LaunchAgents/com.focusledger.notch.plist")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(PLIST)
    subprocess.run(["launchctl", "load", path])
    print(f"Installed LaunchAgent → {path}")
    print("FocusLedger's notch companion will greet you at every login.")


def main():
    if "--install-login" in sys.argv:
        install_login()
        return
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)  # no Dock icon
    delegate = App.alloc().init()
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
