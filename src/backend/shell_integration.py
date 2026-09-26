# -*- coding: utf-8 -*-
"""Windows shell integration for Mikage PromptTable.

Making the app discoverable by taskbar search, uTools, ZTools and similar
launchers means putting a shortcut where they look: the user's Start Menu
Programs folder. Windows Search indexes it and those launchers enumerate it. An
App Paths registry entry is added as well, so the app can also be started by
name from Win+R and by tools that resolve executables that way.

Nothing here needs administrator rights: the shortcut goes into the current
user's Start Menu and the registry key lives under HKEY_CURRENT_USER.
"""
import os
import sys
import json
import subprocess
from typing import Dict, Any

APP_NAME = "Mikage PromptTable"
SHORTCUT_NAME = "Mikage PromptTable.lnk"
REG_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\App Paths\MikagePromptTable.exe"
DESCRIPTION = "Mikage PromptTable - AI 画廊与提示词注释工作台"
STATE_FILE = "shell_state.json"


# ---------------------------------------------------------------- paths

def start_menu_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs")


def shortcut_path() -> str:
    return os.path.join(start_menu_dir(), SHORTCUT_NAME)


def launch_command():
    """(target, arguments, working_dir) that the shortcut should run."""
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        return exe, "", os.path.dirname(exe)
    # running from source: use pythonw so no console window appears
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app_py = os.path.join(project, "app.py")
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    target = pyw if os.path.exists(pyw) else sys.executable
    return target, '"%s"' % app_py, project


def icon_path_for(target: str) -> str:
    """Icon for the shortcut: the bundled app icon next to the code/exe."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(target)          # folder holding the exe
        cand = os.path.join(base, "assets", "app.ico")
        if os.path.exists(cand):
            return cand
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cand = os.path.join(base, "src", "assets", "app.ico")
        if os.path.exists(cand):
            return cand
    return target


# ---------------------------------------------------------------- helpers

def _ps(value) -> str:
    """Quote a value for a PowerShell single-quoted string."""
    return "'" + str(value).replace("'", "''") + "'"


def _run_powershell(script: str, timeout: int = 25):
    for exe in ("powershell", "pwsh"):
        try:
            return subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, errors="replace", timeout=timeout)
        except FileNotFoundError:
            continue
        except Exception:
            return None
    return None


def _state_path(data_dir: str) -> str:
    return os.path.join(data_dir, STATE_FILE)


def _read_state(data_dir: str) -> Dict[str, Any]:
    path = _state_path(data_dir)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _write_state(data_dir: str, state: Dict[str, Any]):
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(_state_path(data_dir), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Shell] state write failed: {e}")


# ---------------------------------------------------------------- shortcut

def create_shortcut(data_dir: str, icon_path: str = "") -> Dict[str, Any]:
    """Write the Start Menu shortcut (this is what makes search work)."""
    target, args, workdir = launch_command()
    lnk = shortcut_path()

    if not icon_path:
        icon_path = icon_path_for(target)
    icon_spec = "%s,0" % icon_path

    try:
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
    except Exception as e:
        return {"success": False, "message": "无法创建开始菜单目录: %s" % e}

    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$sc = $ws.CreateShortcut(%s); "
        "$sc.TargetPath = %s; "
        "$sc.Arguments = %s; "
        "$sc.WorkingDirectory = %s; "
        "$sc.IconLocation = %s; "
        "$sc.Description = %s; "
        "$sc.Save(); "
        "if (Test-Path %s) { 'OK' } else { 'MISSING' }"
        % (_ps(lnk), _ps(target), _ps(args), _ps(workdir),
           _ps(icon_spec), _ps(DESCRIPTION), _ps(lnk))
    )
    res = _run_powershell(script)
    if res is None:
        return {"success": False, "message": "找不到 PowerShell，无法创建快捷方式"}
    if res.returncode != 0 or "OK" not in (res.stdout or ""):
        detail = (res.stderr or res.stdout or "").strip().splitlines()
        return {"success": False,
                "message": detail[-1][:200] if detail else "创建快捷方式失败"}
    return {"success": True, "path": lnk, "icon": icon_path}


# ---------------------------------------------------------------- registry

def _write_app_paths(exe: str) -> bool:
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_SUBKEY)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, exe)
        winreg.SetValueEx(key, "Path", 0, winreg.REG_SZ, os.path.dirname(exe))
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"[Shell] registry write failed: {e}")
        return False


def _delete_app_paths() -> bool:
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_SUBKEY)
        return True
    except FileNotFoundError:
        return True
    except Exception as e:
        print(f"[Shell] registry delete failed: {e}")
        return False


def _app_paths_exists() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_SUBKEY):
            return True
    except Exception:
        return False


# ---------------------------------------------------------------- public API

def status(data_dir: str) -> Dict[str, Any]:
    lnk = shortcut_path()
    target, _, _ = launch_command()
    return {
        "registered": os.path.exists(lnk) or _app_paths_exists(),
        "shortcut": lnk,
        "shortcutExists": os.path.exists(lnk),
        "registry": _app_paths_exists(),
        "target": target,
    }


def register(data_dir: str, icon_path: str = "") -> Dict[str, Any]:
    exe, _, _ = launch_command()
    sc = create_shortcut(data_dir, icon_path)
    reg_ok = _write_app_paths(exe)

    state = _read_state(data_dir)
    state.update({"registered": bool(sc.get("success")), "target": exe})
    _write_state(data_dir, state)

    if sc.get("success"):
        return {"success": True, "registry": reg_ok, "shortcut": sc.get("path", ""),
                "message": "已注册：开始菜单、Windows 搜索与启动器都能找到 Mikage PromptTable 了"}
    return {"success": False, "registry": reg_ok,
            "message": sc.get("message", "注册失败")}


def unregister(data_dir: str) -> Dict[str, Any]:
    lnk = shortcut_path()
    removed = False
    try:
        if os.path.exists(lnk):
            os.remove(lnk)
            removed = True
    except Exception as e:
        return {"success": False, "message": "删除快捷方式失败: %s" % e}
    reg_ok = _delete_app_paths()

    state = _read_state(data_dir)
    state["registered"] = False
    _write_state(data_dir, state)

    return {"success": True, "removedShortcut": removed, "registry": reg_ok,
            "message": "已取消注册"}
