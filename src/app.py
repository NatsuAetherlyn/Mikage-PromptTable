import os
import sys
import ctypes
import webview
from backend.storage import StorageManager
from backend.api import JsApi
from backend.model_library import ModelLibrary
from backend.server import start_local_server
from backend import win32utils
from backend import shell_integration
from backend.win32utils import wait_for_hwnd_and_theme

def set_high_dpi_aware():
    """Enable Windows Per-Monitor High-DPI awareness for crisp rendering."""
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass


def get_base_dir():
    """Directory holding bundled assets (web/, assets/) — _MEIPASS when frozen."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_app_root():
    """Project root: exe dir when frozen, src/ parent in dev."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_icon_path(base_dir: str) -> str:
    """Icon for the window / taskbar: the bundled app icon."""
    candidates = [os.path.join(base_dir, "assets", "app.ico")]
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                                       "assets", "app.ico"))
        candidates.append(os.path.join(getattr(sys, "_MEIPASS", ""), "assets", "app.ico"))
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return ""


def find_comfy_models_dir():
    """Common ComfyUI installs to seed the model library with on first run."""
    candidates = [
        r"E:\ComfyUI-aki-v3.2\ComfyUI\models",
        os.path.expanduser(r"~\AppData\Roaming\ComfyUI\models"),
        r"D:\ComfyUI\models",
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return ""


def _notify(message: str, ok: bool):
    """Show a message box — the packaged exe has no console, so `print` alone
    would be invisible for the --register / --unregister flags."""
    if not message:
        return
    try:
        ctypes.windll.user32.MessageBoxW(
            None, message, "Mikage PromptTable",
            0x40 if ok else 0x30)      # MB_ICONINFORMATION / MB_ICONWARNING
    except Exception:
        pass


def main():
    set_high_dpi_aware()

    base_dir = get_base_dir()
    web_dir = os.path.join(base_dir, "web")
    data_dir = os.path.join(get_app_root(), "data")
    os.makedirs(data_dir, exist_ok=True)

    # Headless flags so an installer (or a script) can wire up shell integration
    # without launching the UI:  MikagePromptTable.exe --register / --unregister
    argv = [a.lower() for a in sys.argv[1:]]
    if "--register" in argv or "--unregister" in argv:
        if "--unregister" in argv:
            res = shell_integration.unregister(data_dir)
        else:
            res = shell_integration.register(data_dir)
        print(res.get("message", ""))
        _notify(res.get("message", ""), res.get("success", False))
        return

    # Start local asset server
    _, port = start_local_server(web_dir)
    app_url = f"http://127.0.0.1:{port}/index.html"

    win32utils.set_min_size(1020, 640)      # matches min_size below

    storage = StorageManager(data_dir)
    library = ModelLibrary(data_dir, default_root=find_comfy_models_dir())
    api = JsApi(storage, library)

    window = webview.create_window(
        title="Mikage PromptTable",
        url=app_url,
        js_api=api,
        width=1440,
        height=920,
        min_size=(1020, 640),
        background_color="#0D0F17",
        text_select=True,
        frameless=True,
        easy_drag=False,
        shadow=True,
    )
    api.set_window(window)
    wait_for_hwnd_and_theme(window, get_icon_path(base_dir))

    webview.start(debug=False)


if __name__ == "__main__":
    main()