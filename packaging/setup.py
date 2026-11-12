"""First-party offline installer; built as a self-contained Windows executable."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from install_support import extract_payload, install, install_dir, remove_installed
from settings import BUILD_ID, VERSION, atomic_json

HERE = Path(__file__).resolve().parent


def wait_for_parent(pid):
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if handle:
        try:
            if kernel.WaitForSingleObject(handle, 30000) != 0:
                raise OSError('The uninstaller is still running; no files were removed.')
        finally:
            kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--remove-installed', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--verify-payload', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--install-silent', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    payload = HERE / 'payload.zip'
    if args.verify_payload:
        with tempfile.TemporaryDirectory(prefix='NaviScout-verify-') as stage:
            manifest = extract_payload(payload, stage)
            atomic_json(args.verify_payload, dict(version=VERSION, verified_files=len(manifest['files']),
                                                  app_id=manifest['app_id']))
        return
    if args.install_silent:
        install(payload, sys.executable)
        return
    root = tk.Tk()
    root.title(f'Navi Scout {VERSION} - Setup')
    root.geometry('650x495')
    root.resizable(False, False)
    root.configure(bg='#13221f')
    if args.remove_installed:
        root.withdraw()
        try:
            wait_for_parent(args.remove_installed)
            remove_installed()
            messagebox.showinfo('Navi Scout', 'Navi Scout was removed. Your game, settings and backups were kept.', parent=root)
        except (OSError, ValueError, KeyError) as error:
            messagebox.showerror('Uninstall stopped', str(error), parent=root)
        root.destroy()
        return
    if args.uninstall:
        root.withdraw()
        if messagebox.askyesno('Uninstall Navi Scout',
                               'Remove Navi Scout and its shortcuts?\nYour game, settings and profile backups will be kept.', parent=root):
            destination = Path(tempfile.mkdtemp(prefix='NaviScout-uninstall-')) / 'Remove Navi Scout.exe'
            shutil.copy2(sys.executable, destination)
            subprocess.Popen([str(destination), '--remove-installed', str(os.getpid())],
                             creationflags=subprocess.CREATE_NO_WINDOW)
        root.destroy()
        return
    tk.Label(root, text='NAVI SCOUT', bg='#13221f', fg='#edc35b',
             font=('Georgia', 27, 'bold')).pack(anchor='w', padx=30, pady=(24, 5))
    tk.Label(root, text='A separate companion for your NX2navi adventure', bg='#13221f', fg='#f0eadb',
             font=('Trebuchet MS', 12)).pack(anchor='w', padx=30, pady=(0, 16))
    tk.Label(root, text='Camera-relative collectible radar with edge arrows and alerts\n'
             'Refills for obtained supplies, existing health and magic meters\n'
             'Minigame ammunition and an optional timer freeze\n\n'
             'Includes its runtime. No Python installation or administrator access needed.\n'
             'Uses your own game files; no game, save or collectible catalog is included.',
             bg='#13221f', fg='#aac1b5', justify='left', font=('Trebuchet MS', 10)).pack(anchor='w', padx=30)
    tk.Label(root, text=f'Compatibility: Windows x64 / game build {BUILD_ID}',
             bg='#13221f', fg='#edc35b', font=('Trebuchet MS', 10, 'bold')).pack(anchor='w', padx=30, pady=15)
    desktop = tk.BooleanVar(value=True)
    tk.Checkbutton(root, text='Create a Desktop shortcut', variable=desktop, bg='#13221f',
                   fg='#f0eadb', selectcolor='#1b302b', activebackground='#13221f').pack(anchor='w', padx=26)
    status = tk.StringVar(value='Installs for your Windows account only. Your game stays where it is.')
    tk.Label(root, textvariable=status, wraplength=585, bg='#13221f', fg='#aac1b5',
             justify='left', font=('Trebuchet MS', 9)).pack(fill='x', padx=30, pady=10)
    row = tk.Frame(root, bg='#13221f')
    row.pack(fill='x', padx=30, pady=8)

    def preview_guide():
        candidates = (Path(sys.executable).parent / 'START-HERE.html',
                      install_dir() / 'docs/START-HERE.html', HERE / 'docs/START-HERE.html')
        guide = next(path for path in candidates if path.is_file())
        os.startfile(guide)

    ttk.Button(row, text='Preview screenshots & guide', command=preview_guide).pack(side='left')
    messages = queue.Queue()

    def begin():
        install_button.state(['disabled'])
        status.set('Checking and installing Navi Scout...')
        want_desktop = desktop.get()

        def work():
            try:
                target = install(payload, sys.executable, want_desktop)
                messages.put(('done', target))
            except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as error:
                messages.put(('error', str(error)))

        threading.Thread(target=work, daemon=True).start()

    def poll():
        try:
            kind, value = messages.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        if kind == 'done':
            status.set('Installed. Start Navi Scout to select your game and create its profile backup.')
            install_button.configure(text='Open Navi Scout', command=lambda: subprocess.Popen([str(value / 'NaviScout.exe')], cwd=value))
            install_button.state(['!disabled'])
        else:
            status.set('Installation stopped: ' + value)
            install_button.state(['!disabled'])
        root.after(100, poll)

    install_button = ttk.Button(row, text='Install Navi Scout', command=begin)
    install_button.pack(side='right')
    ttk.Button(row, text='Close', command=root.destroy).pack(side='right', padx=8)
    root.after(100, poll)
    root.mainloop()


if __name__ == '__main__':
    main()
