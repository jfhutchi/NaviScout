"""Recipient-owned game selection, verified backup and local radar preparation."""
import json
from pathlib import Path
import queue
import threading
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from catalog import save_catalog
from settings import BUILD_ID, atomic_json, backup_profile, validate_game
from windows_support import executable_running


def configure(data, force=False):
    data = Path(data)
    config_path = data / 'config.json'
    if config_path.exists() and not force:
        config = json.loads(config_path.read_text(encoding='utf-8'))
        game = validate_game(config['game_dir'])
        catalog = data / 'catalog.local.json'
        if catalog.is_file() and json.loads(catalog.read_text())['game_build'] == BUILD_ID:
            return game
    root = tk.Tk()
    root.title('Navi Scout - Connect your game')
    root.geometry('640x385')
    root.resizable(False, False)
    root.configure(bg='#13221f')
    selected = tk.StringVar()
    result = []
    messages = queue.Queue()
    tk.Label(root, text='CONNECT YOUR NX2NAVI GAME', bg='#13221f', fg='#edc35b',
             font=('Georgia', 17, 'bold')).pack(anchor='w', padx=24, pady=(22, 12))
    tk.Label(root, text='Choose your existing ocarina.exe. Navi Scout stays separate from the game.\n'
             'Close NX2navi once for setup so its profile can be backed up safely.\n'
             'Your radar catalog is generated locally; no game files are downloaded.',
             justify='left', bg='#13221f', fg='#f0eadb', font=('Trebuchet MS', 10)).pack(anchor='w', padx=24)
    tk.Label(root, text=f'Supported game build: {BUILD_ID}  |  Windows x64',
             bg='#13221f', fg='#aac1b5', font=('Trebuchet MS', 9)).pack(anchor='w', padx=24, pady=12)
    row = tk.Frame(root, bg='#13221f')
    row.pack(fill='x', padx=24)
    ttk.Entry(row, textvariable=selected).pack(side='left', fill='x', expand=True)

    def browse():
        path = filedialog.askopenfilename(parent=root, title='Select your NX2navi ocarina.exe',
                                         filetypes=[('NX2navi game', 'ocarina.exe')])
        if path:
            selected.set(path)

    ttk.Button(row, text='Browse...', command=browse).pack(side='right', padx=(8, 0))
    status = tk.StringVar(value='Setup creates a verified profile backup before enabling the companion.')
    tk.Label(root, textvariable=status, wraplength=590, justify='left', bg='#13221f',
             fg='#aac1b5', font=('Trebuchet MS', 10)).pack(fill='x', padx=24, pady=16)

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
            except (OSError, ValueError, KeyError, RuntimeError, struct.error) as error:
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

    row = tk.Frame(root, bg='#13221f')
    row.pack(fill='x', padx=24, pady=8)
    prepare_button = ttk.Button(row, text='Prepare my game', command=prepare)
    prepare_button.pack(side='right')
    ttk.Button(row, text='Cancel', command=root.destroy).pack(side='right', padx=8)
    root.after(100, poll)
    root.mainloop()
    return result[0] if result else None
