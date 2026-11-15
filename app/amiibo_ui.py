"""A single-selection amiibo page using the game's existing reader."""
import logging
from tkinter import ttk
import tkinter as tk

from amiibo_catalog import PRESETS, load_presets
from amiibo_reader import AmiiboReader
from memory import NotReady
from skin import BG, TEXT, MUTED, GOLD


class AmiiboPage(tk.Frame):
    def __init__(self, parent, data_dir, game_dir, get_game, is_closing, demo=False):
        super().__init__(parent, bg=BG)
        self.demo, self.get_game, self.is_closing = demo, get_game, is_closing
        self.search = tk.StringVar()
        self.details = tk.StringVar(value='Select a figure to see its reward type.')
        self.status = tk.StringVar(value='Open the amiibo scanning prompt in the game, then send one figure.')
        self.sent_name = ''
        self.last_error = None
        try:
            self.presets = sorted(PRESETS, key=lambda row: row.name.casefold()) if demo else load_presets(game_dir)
        except (OSError, ValueError, KeyError) as error:
            self.presets = []
            self.status.set(f'Amiibo compatibility unavailable: {error}')
            logging.exception('Could not load game amiibo compatibility')
        self.by_id = {row.tag_id: row for row in self.presets}
        self.reader = AmiiboReader(self.presets)
        tk.Label(self, text='Tap one amiibo', bg=BG, fg=GOLD,
                 font=('Georgia', 12)).pack(anchor='w', padx=9, pady=(5, 3))
        search_row = tk.Frame(self, bg=BG)
        search_row.pack(fill='x', padx=9, pady=(0, 4))
        tk.Label(search_row, text='Find', bg=BG, fg=MUTED,
                 font=('Trebuchet MS', 9)).pack(side='left', padx=(0, 7))
        entry = ttk.Entry(search_row, textvariable=self.search)
        entry.pack(side='left', fill='x', expand=True)
        table = tk.Frame(self, bg=BG)
        table.pack(fill='x', padx=9)
        self.tree = ttk.Treeview(table, show='tree', selectmode='browse', height=5)
        self.tree.column('#0', width=355, minwidth=100)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='x', expand=True)
        scroll.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self.selected)
        self.search.trace_add('write', self.filter_list)
        tk.Label(self, textvariable=self.details, bg=BG, fg=TEXT, anchor='w', justify='left',
                 font=('Trebuchet MS', 9), wraplength=380, height=2).pack(fill='x', padx=9, pady=3)
        buttons = tk.Frame(self, bg=BG)
        buttons.pack(fill='x', padx=9, pady=(0, 3))
        self.send_button = ttk.Button(buttons, text='Send selected amiibo', command=self.send_selected)
        self.send_button.pack(side='left', fill='x', expand=True, padx=(0, 7))
        self.remove_button = ttk.Button(buttons, text='Remove tag', command=self.remove_tag)
        self.remove_button.pack(side='right')
        tk.Label(self, textvariable=self.status, bg=BG, fg=GOLD, anchor='w', justify='left',
                 font=('Trebuchet MS', 9), wraplength=380, height=3).pack(fill='x', padx=9)
        tk.Label(self, text='Enable amiibo in the game options, equip the amiibo item and use it. '
                 'Location restrictions and daily limits follow the game.', bg=BG, fg=MUTED,
                 font=('Trebuchet MS', 8), wraplength=380, justify='left').pack(fill='x', padx=9)
        self.filter_list()
        self.winfo_toplevel().after(100, self.tick)

    def filter_list(self, *_):
        previous = self.tree.selection()
        for item in self.tree.get_children():
            self.tree.delete(item)
        needle = self.search.get().strip().casefold()
        for preset in self.presets:
            if needle in (preset.name + ' ' + preset.reward).casefold():
                self.tree.insert('', 'end', iid=preset.tag_id, text=preset.name)
        if previous and self.tree.exists(previous[0]):
            self.tree.selection_set(previous[0])
        self.selected()

    def selected(self, *_):
        selection = self.tree.selection()
        preset = self.by_id.get(selection[0]) if selection else None
        if preset:
            text = f'{preset.name}\n{preset.reward}'
            if preset.upcoming:
                text += ' (upcoming model)'
            self.details.set(text)
        else:
            self.details.set(f'{len(self.tree.get_children())} compatible figures. Select one to send.')
        self.update_buttons()

    def update_buttons(self):
        ready = not self.demo and self.get_game() is not None and not self.reader.pending
        self.send_button.state(['!disabled'] if ready and self.tree.selection() else ['disabled'])
        self.remove_button.state(['!disabled'] if ready else ['disabled'])

    def report_error(self, error):
        message = str(error)
        self.status.set(message)
        if message != self.last_error:
            logging.warning('Amiibo reader: %s', message)
            self.last_error = message
        self.update_buttons()

    def send_selected(self):
        if self.demo:
            return
        selection = self.tree.selection()
        preset = self.by_id.get(selection[0]) if selection else None
        game = self.get_game()
        if preset is None or game is None:
            self.status.set('Select a compatible figure while NX2navi is running.')
            return
        try:
            self.reader.begin_send(game, preset)
        except (NotReady, OSError, ValueError) as error:
            self.report_error(error)
            return
        self.sent_name = preset.name
        self.status.set('Checking the game amiibo reader...')
        self.update_buttons()

    def remove_tag(self):
        game = self.get_game()
        if self.demo or game is None:
            self.status.set('Start NX2navi to remove a tag from its reader.')
            return
        try:
            self.reader.begin_remove(game)
        except (NotReady, OSError, ValueError) as error:
            self.report_error(error)
            return
        self.status.set('Removing the current tag...')
        self.update_buttons()

    def show_result(self, result):
        messages = {'sent': f'Sent: {self.sent_name}. Check the game for its result.',
                    'not-ready': 'Reader is not scanning. Use the amiibo item in the game, then try again.',
                    'removed': 'Tag removed from the game reader.',
                    'load-failed': 'The game reader could not load the selected virtual tag.'}
        self.status.set(messages[result])
        self.last_error = None
        self.update_buttons()

    def tick(self):
        if self.is_closing():
            return
        if self.reader.calls.pending:
            try:
                result = self.reader.poll()
                if result is not None:
                    self.show_result(result)
            except (NotReady, OSError, ValueError) as error:
                self.report_error(error)
        self.update_buttons()
        self.winfo_toplevel().after(25 if self.reader.pending else 250, self.tick)
