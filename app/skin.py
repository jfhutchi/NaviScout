"""Original Tk controls inspired by NX2navi's in-game umber/gold menus."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk

BG, PANEL, TEXT, MUTED = '#130f0b', '#261d14', '#f5ebd1', '#b3a084'
GOLD, FRAME, ACTIVE = '#edc261', '#6a5030', '#5c4221'
HERE = Path(__file__).resolve().parent
ASSETS = HERE / 'assets' if (HERE / 'assets').is_dir() else HERE.parent / 'assets'


def apply_style(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=BG, foreground=TEXT, font=('Trebuchet MS', 10))
    style.configure('TButton', background=PANEL, foreground=TEXT, bordercolor=FRAME,
                    lightcolor=FRAME, darkcolor=BG, padding=(10, 5))
    style.map('TButton', background=[('active', ACTIVE)], bordercolor=[('focus', GOLD)])
    style.configure('TCombobox', fieldbackground=PANEL, background=ACTIVE, foreground=TEXT,
                    arrowcolor=GOLD, bordercolor=FRAME, lightcolor=FRAME, darkcolor=BG)
    style.map('TCombobox', fieldbackground=[('readonly', PANEL)],
              foreground=[('readonly', TEXT)], selectbackground=[('readonly', PANEL)])
    style.configure('Scout.TNotebook', background=BG, borderwidth=1, bordercolor=FRAME)
    style.configure('Scout.TNotebook.Tab', background=PANEL, foreground=MUTED,
                    padding=(14, 7), bordercolor=FRAME, font=('Georgia', 11))
    style.configure('Treeview', background=BG, fieldbackground=BG, foreground=TEXT,
                    rowheight=24, bordercolor=FRAME, font=('Trebuchet MS', 9))
    style.map('Treeview', background=[('selected', ACTIVE)], foreground=[('selected', GOLD)])
    style.configure('Treeview.Heading', background=PANEL, foreground=GOLD,
                    relief='flat', bordercolor=FRAME, font=('Trebuchet MS', 9, 'bold'))
    style.map('Scout.TNotebook.Tab', background=[('selected', ACTIVE)],
              foreground=[('selected', GOLD)])
    root.option_add('*TCombobox*Listbox.background', PANEL)
    root.option_add('*TCombobox*Listbox.foreground', TEXT)
    icon = ASSETS / 'naviscout.ico'
    if icon.is_file():
        root.iconbitmap(str(icon))


class Switch(tk.Frame):
    def __init__(self, parent, text, variable, textvariable=None, width=None, compact=False):
        super().__init__(parent, bg=PANEL, highlightthickness=1, highlightbackground=FRAME, padx=6, pady=2)
        self.variable = variable
        self.label = tk.Label(self, text=text, textvariable=textvariable, bg=PANEL, fg=TEXT,
                              anchor='w', font=('Trebuchet MS', 9 if compact else 10))
        self.label.pack(side='left', fill='x', expand=True, padx=(0, 6))
        self.track = tk.Canvas(self, width=48, height=22, bg=PANEL, highlightthickness=1,
                               highlightbackground=PANEL, highlightcolor=GOLD, takefocus=1,
                               cursor='hand2')
        self.track.pack(side='right')
        if width:
            self.configure(width=width, height=32)
            self.pack_propagate(False)
        for target in (self, self.label, self.track):
            target.bind('<Button-1>', self.invoke)
        self.track.bind('<space>', self.invoke)
        self.track.bind('<Return>', self.invoke)
        self.trace = variable.trace_add('write', self.draw)
        self.bind('<Destroy>', self.cleanup)
        self.draw()

    def invoke(self, _event=None):
        self.track.focus_set()
        self.variable.set(not self.variable.get())
        return 'break'

    def state_text(self):
        return 'On' if self.variable.get() else 'Off'

    def draw(self, *_):
        c, on = self.track, self.variable.get()
        c.delete('all')
        fill = ACTIVE if on else PANEL
        c.create_line(11, 11, 37, 11, fill=fill, width=20, capstyle='round')
        c.create_oval(1, 1, 47, 21, outline=FRAME)
        x = 37 if on else 11
        c.create_oval(x-8, 3, x+8, 19, fill=GOLD if on else MUTED, outline='')
        c.create_text(15 if on else 33, 11, text=self.state_text(),
                      fill=TEXT if on else MUTED, font=('Trebuchet MS', 7, 'bold'))

    def cleanup(self, event):
        if event.widget is self:
            self.variable.trace_remove('write', self.trace)


class ChoiceStrip(tk.Frame):
    def __init__(self, parent, variable, choices):
        super().__init__(parent, bg=BG)
        self.variable, self.choices = variable, tuple(choices)
        self.buttons = {}
        for value in self.choices:
            button = tk.Button(self, text=value, command=lambda choice=value: self.choose(choice),
                               bg=PANEL, fg=MUTED, activebackground=ACTIVE, activeforeground=GOLD,
                               relief='flat', bd=1, highlightthickness=1, highlightbackground=FRAME,
                               highlightcolor=GOLD, font=('Trebuchet MS', 9), padx=10, pady=3)
            button.pack(side='left', padx=1)
            self.buttons[value] = button
        self.trace = variable.trace_add('write', self.draw)
        self.bind('<Destroy>', self.cleanup)
        self.draw()

    def choose(self, value):
        if value not in self.choices:
            raise ValueError('Unsupported choice')
        self.variable.set(value)

    def draw(self, *_):
        for value, button in self.buttons.items():
            selected = self.variable.get() == value
            button.configure(bg=ACTIVE if selected else PANEL, fg=GOLD if selected else MUTED)

    def cleanup(self, event):
        if event.widget is self:
            self.variable.trace_remove('write', self.trace)
