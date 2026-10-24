import ctypes
import logging
import subprocess

import Quartz
from AppKit import NSEvent, NSSystemDefined, NSWorkspace

log = logging.getLogger("gyromote")

KEYCODES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11,
    "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17,
    "9": 0x19, "7": 0x1A, "8": 0x1C, "0": 0x1D,
    "o": 0x1F, "u": 0x20, "i": 0x22, "p": 0x23,
    "return": 0x24, "l": 0x25, "j": 0x26, "k": 0x28, "n": 0x2D, "m": 0x2E,
    "tab": 0x30, "space": 0x31, "escape": 0x35,
    "delete": 0x33, "backspace": 0x33,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61,
    "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
    "home": 0x73, "end": 0x77, "pageup": 0x74, "pagedown": 0x79,
    "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E,
    "minus": 0x1B, "equal": 0x18,
}

MODIFIERS = {
    "cmd": (Quartz.kCGEventFlagMaskCommand, 0x37),
    "shift": (Quartz.kCGEventFlagMaskShift, 0x38),
    "alt": (Quartz.kCGEventFlagMaskAlternate, 0x3A),
    "opt": (Quartz.kCGEventFlagMaskAlternate, 0x3A),
    "ctrl": (Quartz.kCGEventFlagMaskControl, 0x3B),
}

MOUSE_BUTTONS = {
    "left": (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft),
    "right": (Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight),
    "middle": (Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp, Quartz.kCGMouseButtonCenter),
}

SPACES_KEYCODES = {"spaces.left": 123, "spaces.right": 124}

MEDIA_KEY_CODES = {"media.volume_up": 0, "media.volume_down": 1, "media.mute": 7, "media.play_pause": 16}

MODIFIER_MASK = (Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift
                 | Quartz.kCGEventFlagMaskAlternate | Quartz.kCGEventFlagMaskControl)


def parse_combo(combo):
    parts = combo.lower().split("+")
    keyname = parts[-1]
    if keyname not in KEYCODES:
        raise ValueError(f"unknown key: {keyname}")
    mods = []
    for mod in parts[:-1]:
        if mod not in MODIFIERS:
            raise ValueError(f"unknown modifier: {mod}")
        mods.append(MODIFIERS[mod])
    return KEYCODES[keyname], mods


def parse_mouse(spec):
    """'alt+left_down' -> (flags, [(flag, keycode)...], 'left_down')"""
    *mod_names, what = spec.split("+")
    mods = []
    for m in mod_names:
        if m not in MODIFIERS:
            raise ValueError(f"unknown modifier: {m}")
        mods.append(MODIFIERS[m])
    flags = 0
    for flag, _ in mods:
        flags |= flag
    return flags, mods, what


def _post_keyboard_event(keycode, flags, down):
    ev = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
    # arrow keys natively carry Fn/NumPad flags (some apps ignore an arrow without them); modifiers are ours only, never the system state
    Quartz.CGEventSetFlags(ev, (Quartz.CGEventGetFlags(ev) & ~MODIFIER_MASK) | flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


# Mission Control and Spaces react only to real modifier key presses; a flag on the key event is not enough
def post_key(keycode, mods, down):
    flags = 0
    if down:
        for flag, mod_code in mods:
            flags |= flag
            _post_keyboard_event(mod_code, flags, True)
        _post_keyboard_event(keycode, flags, True)
    else:
        for flag, _ in mods:
            flags |= flag
        _post_keyboard_event(keycode, flags, False)
        for flag, mod_code in reversed(mods):
            flags &= ~flag
            _post_keyboard_event(mod_code, flags, False)
        post_flags_reset()


def post_flags_reset():
    # a mouse event with a modifier flag leaves it in the system state until the next flagless mouse event: later keys get a stuck Alt
    ev = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, current_mouse_location(), 0)
    Quartz.CGEventSetFlags(ev, 0)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def current_mouse_location():
    return Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))


def post_mouse_button(button, down, flags=0):
    down_type, up_type, btn = MOUSE_BUTTONS[button]
    ev = Quartz.CGEventCreateMouseEvent(None, down_type if down else up_type, current_mouse_location(), btn)
    Quartz.CGEventSetFlags(ev, Quartz.CGEventGetFlags(ev) | flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def post_click(button, flags=0):
    post_mouse_button(button, True, flags)
    post_mouse_button(button, False, flags)


def post_pointer_move(dx, dy, dragging, flags=0):
    pos = current_mouse_location()
    # ponytail: clamps to the main display only; union of CGGetActiveDisplayList bounds if multi-monitor is needed
    bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    x = min(max(pos.x + dx, bounds.origin.x), bounds.origin.x + bounds.size.width - 1)
    y = min(max(pos.y + dy, bounds.origin.y), bounds.origin.y + bounds.size.height - 1)
    ev_type = Quartz.kCGEventLeftMouseDragged if dragging else Quartz.kCGEventMouseMoved
    ev = Quartz.CGEventCreateMouseEvent(None, ev_type, (x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventSetFlags(ev, Quartz.CGEventGetFlags(ev) | flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def post_modifiers(mods, down):
    flags = 0
    for flag, code in (mods if down else reversed(mods)):
        flags = (flags | flag) if down else (flags & ~flag)
        _post_keyboard_event(code, flags, down)


def post_scroll(lines):
    ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, lines)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def post_media_key(key_code):
    for down in (True, False):
        flags = 0xA00 if down else 0xB00
        data1 = (key_code << 16) | ((0xA if down else 0xB) << 8)
        ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            NSSystemDefined, (0, 0), flags, 0, 0, 0, 8, data1, -1)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev.CGEvent())


def switch_space(action):
    # Mission Control ignores a synthetic Ctrl+arrow from CGEvent; System Events gets through
    subprocess.Popen(["osascript", "-e", f'tell application "System Events" to key code {SPACES_KEYCODES[action]} using control down'])


def frontmost_bundle_id():
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.bundleIdentifier() if app else None


_AX = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
_CF = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")


def accessibility_trusted() -> bool:
    return bool(_AX.AXIsProcessTrusted())


def request_accessibility() -> bool:
    if accessibility_trusted():
        return True
    # under launchd the python binary itself needs the grant; the prompt adds it to the Accessibility list
    keys = (ctypes.c_void_p * 1)(ctypes.c_void_p.in_dll(_AX, "kAXTrustedCheckOptionPrompt"))
    vals = (ctypes.c_void_p * 1)(ctypes.c_void_p.in_dll(_CF, "kCFBooleanTrue"))
    _CF.CFDictionaryCreate.restype = ctypes.c_void_p
    _CF.CFDictionaryCreate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
    opts = _CF.CFDictionaryCreate(None, keys, vals, 1,
        ctypes.addressof(ctypes.c_char.in_dll(_CF, "kCFTypeDictionaryKeyCallBacks")),
        ctypes.addressof(ctypes.c_char.in_dll(_CF, "kCFTypeDictionaryValueCallBacks")))
    _AX.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
    _AX.AXIsProcessTrustedWithOptions(opts)
    log.warning("no Accessibility for this process: System Settings > Privacy & Security > Accessibility")
    return False
