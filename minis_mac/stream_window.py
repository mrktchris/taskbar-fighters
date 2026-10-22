"""The streamer-mode window on macOS (growth, EXPERIMENTAL - written on Windows, not yet run on a Mac: MAC-HANDOFF MAC-23).

An ordinary titled, closable, resizable NSWindow (normal level, not a panel, not click-through) whose content is one
layer showing the composited frame minis_core/stream.py hands over, scaled with nearest filtering.  The stream process
switches itself to a regular app (a Dock icon, Cmd-Tab) so capture tools list the window.  --transparent: the window is
not opaque and its background is clear, so the frame's alpha shows through (the title bar stays).

Nothing here reads the screen or another window.
"""
from __future__ import annotations
from AppKit import NSColor, NSView, NSWindow
from Foundation import NSMakeRect

from . import shell

TITLED, CLOSABLE, MINIATURIZABLE, RESIZABLE = 1 << 0, 1 << 1, 1 << 2, 1 << 3
REGULAR = shell._k(shell.AppKit, 'NSApplicationActivationPolicyRegular', 0)


class StreamWindow:
    def __init__(self, title, w, h, transparent=False, bg=(0, 255, 0)):
        a = shell.app()
        try:
            a.setActivationPolicy_(REGULAR)                    # a normal app while streaming: Dock icon, listed by capture tools
        except Exception:
            pass
        self.transparent, self.bg = bool(transparent), tuple(bg)
        self.closed = False
        style = TITLED | CLOSABLE | MINIATURIZABLE | RESIZABLE
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(160, 160, int(w), int(h)), style,
                                                                              shell.BUFFERED, False)
        if win is None:
            raise shell.MacBackendError('could not create the stream window')
        win.setTitle_(str(title))
        win.setReleasedWhenClosed_(False)
        win.setMinSize_((160, 60))
        if self.transparent:
            win.setOpaque_(False)
            win.setBackgroundColor_(NSColor.clearColor())
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, int(w), int(h)))
        self.layer = shell.new_layer()                         # nearest filtering: crisp pixels on Retina
        self.layer.setContentsScale_(1.0)
        v.setLayer_(self.layer)
        v.setWantsLayer_(True)
        win.setContentView_(v)
        self.win, self.view = win, v
        win.makeKeyAndOrderFront_(None)
        shell.activate()

    def client_size(self):
        f = self.view.frame()
        return max(1, int(f.size.width)), max(1, int(f.size.height))

    def present(self, img):
        if self.closed:
            return False
        cg = shell.cgimage(img)

        def apply():
            w, h = self.client_size()
            self.layer.setFrame_(NSMakeRect(0, 0, w, h))
            self.layer.setContents_(cg)
        shell._no_anim(apply)
        return True

    def pump(self):
        if self.closed:
            return False
        shell.pump_events(0.0)
        if not self.win.isVisible() and not self.win.isMiniaturized():
            self.closed = True                                 # the red close button
        return not self.closed

    def wait(self, seconds):
        shell.pump_events(max(0.0, min(0.5, seconds)))

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.win.orderOut_(None)
                self.win.close()
            except Exception:
                pass
