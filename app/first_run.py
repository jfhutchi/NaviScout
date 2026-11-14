"""Recipient-owned game selection, verified backup and local radar preparation."""
import json
from pathlib import Path
import queue
import threading
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from settings import BUILD_ID, atomic_json, backup_profile, validate_game
from windows_support import executable_running
from skin import apply_style
from catalog import CATALOG_VERSION, save_catalog


def configure(data, force=False):
    data = Path(data)
    config_path = data / 'config.json'
    if config_path.exists() and not force:
        config = json.loads(config_path.read_text(encoding='utf-8'))
        game = validate_game(config['game_dir'])
        catalog = data / 'catalog.local.json'
        if catalog.is_file():
            current = json.loads(catalog.read_text())
            if current['game_build'] == BUILD_ID:
                if current.get('catalog_version') != CATALOG_VERSION:
                    save_catalog(game, catalog)
                return game
    root = tk.Tk()
    apply_style(root)
    root.title('Navi Scout - Connect your game')
    root.geometry('640x385')
    root.resizable(False, False)
    root.configure(bg='#130f0b')
    selected = tk.StringVar()
    result = []
    messages = queue.Queue()
    tk.Label(root, text='CONNECT YOUR NX2NAVI GAME', bg='#130f0b', fg='#edc261',
             font=('Georgia', 17, 'bold')).pack(anchor='w', padx=24, pady=(22, 12))
    tk.Label(root, text='Choose your existing ocarina.exe. Navi Scout stays separate from the game.\n'
             'Close NX2navi once for setup so its profile can be backed up safely.\n'
             'Your radar catalog is generated locally; no game files are downloaded.',
             justify='left', bg='#130f0b', fg='#f5ebd1', font=('Trebuchet MS', 10)).pack(anchor='w', padx=24)
    tk.Label(root, text=f'Tested on NX2navi 0.9.2 / 0.10.1  |  Build {BUILD_ID}',
             bg='#130f0b', fg='#b3a084', font=('Trebuchet MS', 9)).pack(anchor='w', padx=24, pady=12)
    row = tk.Frame(root, bg='#130f0b')
    row.pack(fill='x', padx=24)
    ttk.Entry(row, textvariable=selected).pack(side='left', fill='x', expand=True)

    def browse():
        path = filedialog.askopenfilename(parent=root, title='Select your NX2navi ocarina.exe',
                                         filetypes=[('NX2navi game', 'ocarina.exe')])
        if path:
            selected.set(path)

    ttk.Button(row, text='Browse...', command=browse).pack(side='right', padx=(8, 0))
    status = tk.StringVar(value='Setup creates a verified profile backup before enabling the companion.')
    tk.Label(root, textvariable=status, wraplength=590, justify='left', bg='#130f0b',
             fg='#b3a084', font=('Trebuchet MS', 10)).pack(fill='x', padx=24, pady=16)

    def prepare():
        try:
            game = validate_game(selected.get())
            if executable_running(game / 'ocarina.exe'):
                raise ValueError('Close NX2navi, then choose Prepare my game again. Your game was not stopped.')
        except (OSError, ValueError) as error:
            messagebox.showerror('Game setup', str(error), parent=root)
            return
        prepare_button.state(['disabled'])
        status.set('Backing up the profile and generating your private radar catalog...')

        def work():
            try:
                backup = backup_profile(game, data / 'backups')
                if executable_running(game / 'ocarina.exe'):
                    raise ValueError('NX2navi started during backup. Close it and prepare again.')
                save_catalog(game, data / 'catalog.local.json')
                atomic_json(config_path, dict(game_dir=str(game), game_build=BUILD_ID,
                                             backup=str(backup) if backup else None))
                messages.put(('done', game))
            except (OSError, ValueError, KeyError, RuntimeError, ImportError, struct.error) as error:
                messages.put(('error', str(error)))

        threading.Thread(target=work, daemon=True).start()

    def poll():
        try:
            kind, value = messages.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        if kind == 'done':
            result.append(value)
            root.destroy()
            return
        prepare_button.state(['!disabled'])
        status.set('Setup stopped. No cheats have been started.')
        messagebox.showerror('Game setup', value, parent=root)
        root.after(100, poll)

    row = tk.Frame(root, bg='#130f0b')
    row.pack(fill='x', padx=24, pady=8)
    prepare_button = ttk.Button(row, text='Prepare my game', command=prepare)
    prepare_button.pack(side='right')
    ttk.Button(row, text='Cancel', command=root.destroy).pack(side='right', padx=8)
    root.after(100, poll)
    root.mainloop()
    return result[0] if result else None
