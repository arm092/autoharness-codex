"""Finish Setup by gracefully restarting the desktop app and opening its plugin page.

Never terminates a process forcibly, changes hook trust, or sends a chat message.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import quote


def desktop_executable():
    # MSIX registration is the stable locator; do not pin an app version directory.
    shell = str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
    query = "Get-AppxPackage OpenAI.Codex | Select-Object -First 1 -ExpandProperty InstallLocation"
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', query],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW)
    location = result.stdout.strip()
    if result.returncode == 0 and location:
        executable = Path(location)/'app/ChatGPT.exe'
        if executable.is_file():
            return executable.resolve()
    raise RuntimeError('Codex desktop app was not found. Restart it manually; the plugin is already installed.')


class ProcessEntry(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
        ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
        ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
        ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
        ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR*260)]


class UniqueProcess(ctypes.Structure):
    _fields_ = [('pid', wintypes.DWORD), ('started', wintypes.FILETIME)]


def desktop_processes(executable):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)]*4]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    entry, matches = ProcessEntry(), []
    entry.dwSize = ctypes.sizeof(entry)
    target = os.path.normcase(str(Path(executable).resolve()))
    try:
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.szExeFile.casefold() == Path(executable).name.casefold():
                handle = kernel.OpenProcess(0x1000, False, entry.th32ProcessID)
                if not handle:
                    raise RuntimeError('Cannot inspect a Codex desktop process; restart manually.')
                try:
                    buffer, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
                    if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if os.path.normcase(str(Path(buffer.value).resolve())) == target:
                        started, ended, system, user = (wintypes.FILETIME() for _ in range(4))
                        if not kernel.GetProcessTimes(handle, ctypes.byref(started), ctypes.byref(ended), ctypes.byref(system), ctypes.byref(user)):
                            raise ctypes.WinError(ctypes.get_last_error())
                        matches.append((UniqueProcess(entry.th32ProcessID, started), entry.th32ParentProcessID))
                finally:
                    kernel.CloseHandle(handle)
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    pids = {process.pid for process, parent in matches}
    return [process for process, parent in matches if parent not in pids]


def graceful_shutdown(processes):
    if not processes:
        return
    manager = ctypes.WinDLL('rstrtmgr', use_last_error=True)
    manager.RmStartSession.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR]
    manager.RmRegisterResources.argtypes = [wintypes.DWORD, wintypes.UINT, ctypes.c_void_p,
        wintypes.UINT, ctypes.POINTER(UniqueProcess), wintypes.UINT, ctypes.c_void_p]
    manager.RmShutdown.argtypes = [wintypes.DWORD, wintypes.ULONG, ctypes.c_void_p]
    manager.RmEndSession.argtypes = [wintypes.DWORD]
    session, key = wintypes.DWORD(), ctypes.create_unicode_buffer(33)
    code = manager.RmStartSession(ctypes.byref(session), 0, key)
    if code:
        raise RuntimeError(f'Windows could not start graceful restart ({code}). Restart Codex manually.')
    try:
        registered = (UniqueProcess*len(processes))(*processes)
        code = manager.RmRegisterResources(session, 0, None, len(processes), registered, 0, None)
        if code == 0:
            # Zero flags: explicitly no RmForceShutdown and no taskkill fallback.
            code = manager.RmShutdown(session, 0, None)
        if code:
            raise RuntimeError(f'Codex could not close gracefully ({code}). Finish active work and restart it manually.')
    finally:
        manager.RmEndSession(session)


def finish(root, restart, open_plugin, *, locate=desktop_executable, processes=desktop_processes,
           shutdown=graceful_shutdown, launch=None):
    root = Path(root).resolve()
    state = json.loads((root/'install-state.json').read_text(encoding='utf-8'))
    if not state.get('registered') or Path(state['plugin']).resolve() != root/'plugin':
        raise RuntimeError('The plugin is not registered; desktop actions were skipped.')
    if not restart and not open_plugin:
        return {'status': 'skipped'}
    profile = (Path.home()/'.codex').resolve()
    inherited = Path(os.environ.get('CODEX_HOME', str(profile))).resolve()
    if Path(state['home']).resolve() != profile or inherited != profile:
        raise RuntimeError('The plugin was installed into a different Codex profile. Open that profile manually.')
    if restart:
        executable = locate()
        shutdown(processes(executable))
        # Never start a second instance if an app declined or delayed its shutdown.
        deadline = time.monotonic()+10
        while processes(executable):
            if time.monotonic() >= deadline:
                raise RuntimeError('Codex is still running. Restart it manually after active work finishes.')
            time.sleep(0.2)
    url = 'codex://'
    if open_plugin:
        marketplace = root/'plugin/.agents/plugins/marketplace.json'
        url = 'codex://plugins/autoharness-codex?marketplacePath='+quote(str(marketplace), safe='')
    (launch or os.startfile)(url)
    return {'status': 'opened', 'restart': restart, 'plugin_page': open_plugin}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--restart', action='store_true')
    parser.add_argument('--open-plugin', action='store_true')
    args = parser.parse_args()
    time.sleep(0.75)  # Allow the closing Setup window to release focus.
    try:
        result = finish(args.root, args.restart, args.open_plugin)
        code = 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result, code = {'status': 'failed', 'error': str(error)}, 1
        ctypes.windll.user32.MessageBoxW(None, str(error), 'AutoHarness – restart Codex', 0x10)
    (Path(args.root)/'finish-result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    raise SystemExit(code)
