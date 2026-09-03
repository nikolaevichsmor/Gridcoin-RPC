import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import threading

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

WM_USER = 0x0400
WM_TRAY = WM_USER + 20
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
IDI_APPLICATION = 32512

WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203
WM_COMMAND = 0x0111
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_GRAYED = 0x00000001
TPM_RIGHTBUTTON = 0x0002

ID_TITLE = 1001
ID_TOGGLE = 1002
ID_EXIT = 1003

# Configure ctypes function signatures for 64-bit Windows
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_uint64, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p
]
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT
]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.LoadIconW.restype = wintypes.HICON


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


def _get_icon_file_path() -> str:
    """Find path to app_icon.ico in PyInstaller bundle or project root."""
    if hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / "app_icon.ico"
        if p.is_file():
            return str(p)
    p = Path(__file__).resolve().parent / "app_icon.ico"
    if p.is_file():
        return str(p)
    return ""


class PureWindowsTray:
    def __init__(self, tooltip: str, on_toggle, on_exit):
        self.tooltip = tooltip
        self.on_toggle = on_toggle
        self.on_exit = on_exit
        self.hwnd = None
        self.nid = None
        self.is_enabled = True
        self._thread = None
        self._running = False
        self._proc = None

    def start(self):
        if sys.platform != "win32":
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self.hwnd and self.nid:
            try:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
                user32.PostMessageW(self.hwnd, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            if lparam == WM_RBUTTONUP:
                self._show_menu()
                return 0
            elif lparam == WM_LBUTTONDBLCLK:
                self.is_enabled = not self.is_enabled
                if self.on_toggle:
                    self.on_toggle(self.is_enabled)
                return 0
        elif msg == WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == ID_TOGGLE:
                self.is_enabled = not self.is_enabled
                if self.on_toggle:
                    self.on_toggle(self.is_enabled)
            elif cmd == ID_EXIT:
                if self.on_exit:
                    self.on_exit()
                self.stop()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self):
        hmenu = user32.CreatePopupMenu()
        user32.AppendMenuW(hmenu, MF_STRING | MF_GRAYED, ID_TITLE, "Gridcoin Discord RPC")
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        toggle_label = "Turn Off Presence" if self.is_enabled else "Turn On Presence"
        user32.AppendMenuW(hmenu, MF_STRING, ID_TOGGLE, toggle_label)
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(hmenu, MF_STRING, ID_EXIT, "Exit")

        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        user32.TrackPopupMenu(hmenu, TPM_RIGHTBUTTON, pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, 0, 0, 0)
        user32.DestroyMenu(hmenu)

    def _run_loop(self):
        try:
            class_name = f"GridcoinTray_{id(self)}"
            self._proc = WNDPROC(self._wnd_proc)

            hinst = kernel32.GetModuleHandleW(None)
            wndclass = WNDCLASSEXW()
            wndclass.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wndclass.lpfnWndProc = self._proc
            wndclass.hInstance = hinst
            wndclass.lpszClassName = class_name
            user32.RegisterClassExW(ctypes.byref(wndclass))

            self.hwnd = user32.CreateWindowExW(
                0, class_name, "GridcoinTrayWindow", 0, 0, 0, 0, 0, 0, 0, hinst, None
            )

            # Load custom icon
            hicon = None
            icon_file = _get_icon_file_path()
            if icon_file:
                hicon = user32.LoadImageW(None, icon_file, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            if not hicon:
                hicon = user32.LoadIconW(hinst, ctypes.cast(1, wintypes.LPCWSTR))
            if not hicon:
                hicon = user32.LoadIconW(0, ctypes.cast(IDI_APPLICATION, wintypes.LPCWSTR))

            self.nid = NOTIFYICONDATAW()
            self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            self.nid.hWnd = self.hwnd
            self.nid.uID = 1
            self.nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            self.nid.uCallbackMessage = WM_TRAY
            self.nid.hIcon = hicon
            self.nid.szTip = self.tooltip[:127]

            shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid))

            msg = wintypes.MSG()
            while self._running and user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            pass
