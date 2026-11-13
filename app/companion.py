"""Local radar and capacity-limited resource controls for NX2navi."""
import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from tkinter import messagebox, ttk
from types import SimpleNamespace
import winsound

from core import RESOURCES, collected, nearby, radar_edge_target, radar_offset
from hotkeys import GlobalHotkey
from memory import Game, NotReady
from player import PlayerModifiers
from running import RunSpeed
from stealth import EnemyStealth
from diving import DIVE_MODES, DiveLimit
from timers import TimerHold
from skin import ASSETS, BG, PANEL, TEXT, MUTED, GOLD, FRAME, Switch, ChoiceStrip, apply_style
from settings import VERSION, atomic_json, user_data, validate_game

HERE = Path(__file__).resolve().parent
HEART, LINK = '#ff8b9e', '#74e0c6'


def migrate_preferences(settings):
    settings = dict(settings)
    if not settings.get('run_swim_v2'):
        settings['roll_speed'] = settings.get('run_speed', False)
        settings['run_speed'] = False
    if 'link_auto' not in settings:
        settings['link_auto'] = settings.get('auto', False)
    if not any(key.startswith('minigame_refill_') for key in settings):
        settings['minigames'] = settings.get('minigames', True) and settings.get('auto', False)
        for name in ('bombchus', 'seeds', 'arrows'):
            settings[f'minigame_refill_{name}'] = settings.get(f'refill_{name}', True)
    return settings


class Companion:
    def __init__(self, game_dir, data_dir, launch=False, demo=False):
        self.demo = demo
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.game_dir = Path(game_dir)
        self.executable = self.game_dir / "ocarina.exe"
        self.catalog = [] if demo else json.loads((self.data_dir / 'catalog.local.json').read_text())['items']
        self.named = {x['flag'] for x in self.catalog if x.get('flag')}
        self.game = None if demo else Game.find(self.executable)
        if launch and not self.game:
            subprocess.Popen([str(self.executable)], cwd=self.game_dir)
        self.root = tk.Tk()
        self.root.title('Navi Scout - Radar & Refills')
        apply_style(self.root)
        height = min(1000, self.root.winfo_screenheight() - 70)
        self.root.geometry(f'440x{height}+{max(10, self.root.winfo_screenwidth() - 465)}+20')
        self.root.resizable(False, False)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 1.0 if demo else 0.94)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.report_callback_exception = self.callback_error
        self.auto = tk.BooleanVar(value=False)
        self.link_auto = tk.BooleanVar(value=False)
        self.run_speed = tk.BooleanVar(value=False)
        self.roll_speed = tk.BooleanVar(value=False)
        self.jump_height = tk.BooleanVar(value=False)
        self.invisible = tk.BooleanVar(value=False)
        self.invisible_text = tk.StringVar(value='Enemies: normal detection')
        self.enemy_stealth = EnemyStealth()
        self.player_modifiers = PlayerModifiers()
        self.run_modifier = RunSpeed()
        self.movement_text = tk.StringVar(value='Movement: normal')
        self.dive_mode = tk.StringVar(value='Off')
        self.dive_text = tk.StringVar(value='Dive limit: normal scale depth')
        self.dive_limit = DiveLimit()
        self.minigames = tk.BooleanVar(value=False)
        self.minigame_enabled = {name: tk.BooleanVar(value=True) for name in ('bombchus', 'seeds', 'arrows')}
        self.minigame_text = tk.StringVar(value='Minigame ammo: waiting for a round')
        self.freeze_timer = tk.BooleanVar(value=False)
        self.timer_text = tk.StringVar(value='Timer: waiting for a timed minigame')
        self.timer_hold = TimerHold()
        self.timer_state = None
        self.sound = tk.BooleanVar(value=True)
        self.skulls = tk.BooleanVar(value=True)
        self.hearts = tk.BooleanVar(value=True)
        self.range = tk.IntVar(value=100)
        self.alert_radius = tk.IntVar(value=25)
        self.area = tk.StringVar(value='Waiting for NX2navi')
        self.status = tk.StringVar(value='Load your latest save. F8 hides/shows this window.')
        self.alert = tk.StringVar(value='Collectible proximity alerts enabled')
        self.counts = tk.StringVar(value='100 Skulltulas  /  36 heart pieces')
        self.resource_text = {name: tk.StringVar(value=f'{name.replace("_", " ").title()}: waiting') for name in RESOURCES}
        self.enabled = {name: tk.BooleanVar(value=True) for name in RESOURCES}
        preferences = self.data_dir / 'preferences.local.json'
        if preferences.exists() and not demo:
            settings = migrate_preferences(json.loads(preferences.read_text()))
            for key, var in self.preference_vars().items():
                if key in settings:
                    value = settings[key]
                    if isinstance(var, tk.BooleanVar) and type(value) is not bool:
                        raise ValueError(f'Invalid preference: {key}')
                    if key == 'range' and value not in (40, 60, 100, 200, 500):
                        raise ValueError('Invalid radar range')
                    if key == 'alert_radius' and value not in (10, 15, 25, 40, 60):
                        raise ValueError('Invalid alert radius')
                    if key == 'dive_mode' and value not in DIVE_MODES:
                        raise ValueError('Invalid dive limit preference')
                    var.set(value)
        self.last_near = set()
        self.last_sound = 0.0
        self.next_attach = 0.0
        self.next_record = 0.0
        self.once = False
        self.link_once = False
        self.last_rows = []
        self.hidden = False
        self.stopped = False
        self.closing = False
        self.close_job = None
        self.had_game = self.game is not None
        try:
            self.hotkey = None if demo else GlobalHotkey()
        except OSError as error:
            logging.error('F8 registration failed: %s', error)
            self.hotkey = None
        self.build_ui()
        if demo:
            self.area.set('PREVIEW - SAMPLE DATA')
            self.counts.set('Illustrative demo / no game is attached')
            self.alert.set('Gold arrow = nearest target beyond radar range')
            self.status.set('Demonstration only. No game memory is read or changed.')
            examples = {'rupees': 'Rupees: 500/500', 'sticks': 'Sticks: 10/10', 'seeds': 'Seeds: 50/50',
                        'nuts': 'Nuts: 20/20', 'bombs': 'Bombs: 40/40', 'bombchus': 'Bombchus: 40/40',
                        'arrows': 'Arrows: locked', 'magic_beans': 'Magic Beans: 10/10',
                        'scrub_seeds': 'Scrub Seeds: 30/30', 'health': 'Health: 7/7 hearts', 'magic': 'Magic: 100%'}
            for name, var in self.resource_text.items():
                var.set(examples[name])
            self.freeze_timer.set(True)
            self.minigame_text.set('Sample: minigame Bombchus 10/10')
            self.timer_text.set('Sample: Diving 0:45 (FROZEN)')
            self.draw([dict(kind='skull', dx=220, dz=-120, dy=8, distance=251)], (0, -1))
            return
        for var in self.preference_vars().values():
            var.trace_add('write', self.save_preferences)
        self.root.after(250, self.tick)
        self.root.after(50, self.refresh_radar)
        self.root.after(25, self.poll_hotkey)
        self.root.after(100, self.refresh_timer)
        self.root.after(100, self.refresh_player)
        self.root.after(100, self.refresh_stealth)
        self.root.after(100, self.refresh_diving)

    def preference_vars(self):
        return dict(auto=self.auto, link_auto=self.link_auto, run_speed=self.run_speed, roll_speed=self.roll_speed,
                    jump_height=self.jump_height, invisible=self.invisible,
                    minigames=self.minigames, freeze_timer=self.freeze_timer,
                    dive_mode=self.dive_mode,
                    sound=self.sound, skulls=self.skulls, hearts=self.hearts,
                    range=self.range, alert_radius=self.alert_radius,
                    **{f'refill_{name}': var for name, var in self.enabled.items()},
                    **{f'minigame_refill_{name}': var for name, var in self.minigame_enabled.items()})

    def save_preferences(self, *_):
        if self.demo:
            return
        settings = {key: var.get() for key, var in self.preference_vars().items()}
        settings['run_swim_v2'] = True
        target = self.data_dir / 'preferences.local.json'
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(settings, indent=2))
        temp.replace(target)

    def label(self, text=None, variable=None, **kw):
        parent = kw.pop('parent', self.root)
        options = dict(bg=BG, fg=TEXT, anchor='w', font=('Trebuchet MS', 10))
        options.update(kw)
        widget = tk.Label(parent, text=text, textvariable=variable, **options)
        widget.pack(fill='x', padx=14, pady=2)
        return widget

    def build_ui(self):
        header = tk.Frame(self.root, bg=PANEL, highlightthickness=1, highlightbackground=FRAME)
        header.pack(fill='x', padx=12, pady=(10, 6))
        icon = ASSETS / 'naviscout.png'
        if icon.is_file():
            original = tk.PhotoImage(file=str(icon))
            self.header_icon = original.subsample(max(1, original.width() // 54))
            tk.Label(header, image=self.header_icon, bg=PANEL).pack(side='left', padx=(10, 6), pady=4)
        title = tk.Frame(header, bg=PANEL)
        title.pack(side='left', pady=7)
        tk.Label(title, text='Navi Scout', bg=PANEL, fg=GOLD,
                 font=('Georgia', 23, 'bold')).pack(anchor='w')
        tk.Label(title, text='RADAR  /  TRAINER', bg=PANEL, fg=MUTED,
                 font=('Trebuchet MS', 8)).pack(anchor='w')
        self.label(variable=self.area, font=('Georgia', 11, 'bold'))
        self.label(variable=self.counts, fg=MUTED, font=('Trebuchet MS', 9))
        self.canvas = tk.Canvas(self.root, width=408, height=230, bg=PANEL,
                                highlightthickness=1, highlightbackground=FRAME)
        self.canvas.pack(padx=14, pady=5)
        self.label(variable=self.alert, fg=GOLD, wraplength=410, height=2)
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill='x', padx=12)
        for title, var in [('Skulls', self.skulls), ('Hearts', self.hearts), ('Sound', self.sound)]:
            Switch(row, title, var, width=134, compact=True).pack(side='left', padx=1)
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill='x', padx=14, pady=5)
        tk.Label(row, text='Radar m', bg=BG, fg=MUTED).pack(side='left')
        ttk.Combobox(row, textvariable=self.range, values=(40, 60, 100, 200, 500),
                     width=5, state='readonly').pack(side='left', padx=7)
        tk.Label(row, text='Alert m', bg=BG, fg=MUTED).pack(side='left', padx=(24, 0))
        ttk.Combobox(row, textvariable=self.alert_radius, values=(10, 15, 25, 40, 60),
                     width=5, state='readonly').pack(side='left', padx=7)
        self.controls = ttk.Notebook(self.root, style='Scout.TNotebook', height=365)
        self.controls.pack(fill='x', padx=12, pady=(5, 4))
        items, link, games = (tk.Frame(self.controls, bg=BG) for _ in range(3))
        for frame, title in ((items, 'Items'), (link, 'Link'), (games, 'Minigames')):
            self.controls.add(frame, text=title)
        self.label('Owned supplies', parent=items, fg=GOLD, font=('Georgia', 12), pady=5)
        grid = tk.Frame(items, bg=BG)
        grid.pack(fill='x', padx=8)
        supplies = [name for name in RESOURCES if name not in ('health', 'magic')]
        for i, name in enumerate(supplies):
            Switch(grid, '', self.enabled[name], textvariable=self.resource_text[name],
                   width=196, compact=True).grid(row=i // 2, column=i % 2, padx=1, pady=2)
        row = tk.Frame(items, bg=BG)
        row.pack(fill='x', padx=9, pady=9)
        Switch(row, 'Keep topped up', self.auto).pack(side='left', fill='x', expand=True, padx=(0, 7))
        ttk.Button(row, text='Refill once', command=self.refill_once).pack(side='right')
        self.label('Unobtained items remain locked. Caps follow your bags and wallet.',
                   parent=items, fg=MUTED, font=('Trebuchet MS', 9), wraplength=380)
        self.label('Health, magic & abilities', parent=link, fg=GOLD, font=('Georgia', 12), pady=4)
        row = tk.Frame(link, bg=BG)
        row.pack(fill='x', padx=8)
        for name in ('health', 'magic'):
            Switch(row, '', self.enabled[name], textvariable=self.resource_text[name],
                   width=196, compact=True).pack(side='left', padx=1)
        row = tk.Frame(link, bg=BG)
        row.pack(fill='x', padx=9, pady=4)
        Switch(row, 'Keep meters topped up', self.link_auto).pack(side='left', fill='x', expand=True, padx=(0, 7))
        ttk.Button(row, text='Refill once', command=self.refill_link_once).pack(side='right')
        Switch(link, 'Run / swim speed 2x', self.run_speed).pack(fill='x', padx=9, pady=2)
        row = tk.Frame(link, bg=BG)
        row.pack(fill='x', padx=8, pady=2)
        for title, var in [('Roll speed 2x', self.roll_speed), ('Jump height 2x', self.jump_height)]:
            Switch(row, title, var, width=196, compact=True).pack(side='left', padx=1)
        Switch(link, 'Invisible to enemies', self.invisible).pack(fill='x', padx=9, pady=2)
        self.label(variable=self.invisible_text, parent=link, fg=MUTED, font=('Trebuchet MS', 8), wraplength=380)
        self.label(variable=self.movement_text, parent=link, fg=MUTED, font=('Trebuchet MS', 8), wraplength=380)
        row = tk.Frame(link, bg=BG)
        row.pack(fill='x', padx=12, pady=4)
        tk.Label(row, text='Dive limit', bg=BG, fg=GOLD, font=('Georgia', 11)).pack(side='left')
        ChoiceStrip(row, self.dive_mode, DIVE_MODES).pack(side='right')
        self.label(variable=self.dive_text, parent=link, fg=MUTED, font=('Trebuchet MS', 9), wraplength=380)
        self.label('Minigame assists', parent=games, fg=GOLD, font=('Georgia', 12), pady=6)
        Switch(games, 'Keep round ammo topped up', self.minigames).pack(fill='x', padx=9, pady=4)
        for name, var in self.minigame_enabled.items():
            Switch(games, name.title(), var).pack(fill='x', padx=9, pady=2)
        self.label(variable=self.minigame_text, parent=games, fg=MUTED, font=('Trebuchet MS', 9))
        Switch(games, 'Freeze minigame timer', self.freeze_timer).pack(fill='x', padx=9, pady=5)
        self.label(variable=self.timer_text, parent=games, fg=MUTED, font=('Trebuchet MS', 9))
        self.label(variable=self.status, fg=MUTED, font=('Trebuchet MS', 8), wraplength=410, height=3)
        footer = 'F8: hide/show  |  drag title bar to move  |  X: stop trainer'
        if self.demo:
            footer = 'Preview only - sample markers and values'
        elif not self.hotkey:
            footer = 'F8 unavailable (in use). Minimize to hide; X stops assists.'
        self.label(footer, fg=GOLD, font=('Trebuchet MS', 8))

    def refill_once(self):
        self.once = True

    def refill_link_once(self):
        self.link_once = True

    def callback_error(self, kind, error, traceback):
        logging.error('UI callback failed', exc_info=(kind, error, traceback))
        self.once = self.link_once = False
        self.auto.set(False)
        self.link_auto.set(False)
        self.minigames.set(False)
        self.run_speed.set(False)
        self.roll_speed.set(False)
        self.invisible.set(False)
        self.jump_height.set(False)
        self.dive_mode.set('Off')
        self.freeze_timer.set(False)
        self.status.set(f'Error; refills stopped: {error}')
        messagebox.showerror('Navi Scout', str(error), parent=self.root)

    def poll_hotkey(self):
        if self.stopped:
            return
        while self.hotkey:
            try:
                event = self.hotkey.events.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, OSError):
                logging.error('F8 listener failed: %s', event)
                self.status.set(f'F8 listener failed: {event}')
                self.hotkey.close()
                self.hotkey = None
                break
            if event == 'toggle':
                self.hidden = not self.hidden
                if self.hidden:
                    self.root.withdraw()
                else:
                    self.root.deiconify()
                logging.info('F8 toggled radar: %s', 'hidden' if self.hidden else 'shown')
        self.root.after(25, self.poll_hotkey)

    def draw(self, rows, forward):
        c = self.canvas
        c.delete('all')
        cx, cy, size = 204, 119, 83
        radius = self.range.get()
        for r in (size / 2, size):
            c.create_oval(cx-r, cy-r, cx+r, cy+r, outline='#705936', dash=(2, 4))
        c.create_line(cx-size, cy, cx+size, cy, fill='#493824')
        c.create_line(cx, cy-size, cx, cy+size, fill='#493824')
        c.create_text(cx, 12, text=f'CAMERA UP  /  {radius} m', fill=MUTED, font=('Trebuchet MS', 9))
        nx, ny = radar_offset(0, -1, forward)
        c.create_text(cx + (size + 14) * nx, cy + (size + 14) * ny, text='N', fill=GOLD,
                      font=('Trebuchet MS', 10, 'bold'))
        c.create_polygon(cx, cy-7, cx-5, cy+6, cx+5, cy+6, fill=LINK)
        for item in reversed(rows):
            if math.hypot(item['dx'], item['dz']) > radius:
                continue
            rx, ry = radar_offset(item['dx'], item['dz'], forward)
            x, y = cx + size * rx / radius, cy + size * ry / radius
            color = GOLD if item['kind'] == 'skull' else HEART
            if item['kind'] == 'skull':
                c.create_oval(x-4, y-4, x+4, y+4, fill=color, outline=TEXT)
            else:
                c.create_polygon(x, y-6, x+5, y, x, y+6, x-5, y, fill=color, outline=TEXT)
            vertical = '^' if item['dy'] > 3 else 'v' if item['dy'] < -3 else ''
            c.create_text(x+7, y-8, text=f"{item['distance']:.0f}m{vertical}", fill=color,
                          anchor='w', font=('Trebuchet MS', 8))
        edge = radar_edge_target(rows, radius, forward)
        if edge:
            item, ux, uy = edge
            color = GOLD if item['kind'] == 'skull' else HEART
            tip_x, tip_y = cx + size * ux, cy + size * uy
            base_x, base_y = cx + (size - 15) * ux, cy + (size - 15) * uy
            c.create_polygon(tip_x, tip_y, base_x - 7 * uy, base_y + 7 * ux,
                             base_x + 7 * uy, base_y - 7 * ux, fill=color, outline=TEXT, width=1)
            vertical = '^' if item['dy'] > 3 else 'v' if item['dy'] < -3 else ''
            c.create_text(cx + (size - 33) * ux, cy + (size - 33) * uy,
                          text=f"{item['distance']:.0f}m{vertical}", fill=color,
                          font=('Trebuchet MS', 9, 'bold'))
        c.create_text(12, 218, text='Gold = Skulltula     Pink = heart     ^ / v = above / below',
                      fill=MUTED, anchor='w', font=('Trebuchet MS', 8))

    def refresh_radar(self):
        if self.stopped:
            return
        if self.game and self.game.alive():
            try:
                self.draw(self.last_rows, self.game.camera_direction())
            except NotReady:
                self.canvas.delete('all')
                self.canvas.create_text(170, 130, text='Waiting for the scene camera', fill=MUTED)
        self.root.after(50, self.refresh_radar)

    def refresh_timer(self):
        if self.stopped:
            return
        try:
            if not self.game or not self.game.alive():
                raise NotReady('Waiting for NX2navi')
            manager, area, _ = self.game.state()
            timer = self.game.freeze_minigame_timer(manager, area, self.timer_hold, self.freeze_timer.get())
            self.timer_state = timer
            if timer:
                seconds = int(timer['milliseconds'] / 1000)
                mode = 'FROZEN' if timer['frozen'] else 'countdown' if timer['countdown'] else 'elapsed'
                self.timer_text.set(f"{timer['game']}: {seconds // 60}:{seconds % 60:02d} ({mode})")
            else:
                self.timer_text.set('Timer: waiting for a timed minigame')
        except NotReady:
            self.timer_hold.reset()
            self.timer_state = None
            self.timer_text.set('Timer: waiting for active minigame play')
        except (OSError, ValueError) as error:
            self.freeze_timer.set(False)
            self.timer_hold.reset()
            self.timer_state = None
            logging.exception('Timer freeze stopped')
            self.timer_text.set(f'Timer freeze stopped: {error}')
        self.root.after(25 if self.freeze_timer.get() else 250, self.refresh_timer)

    def tick(self):
        if self.stopped:
            return
        now = time.monotonic()
        try:
            if self.game and not self.game.alive():
                self.game.close()
                self.game = None
                if self.had_game:
                    self.close()
                    return
            if not self.game:
                if now < self.next_attach:
                    raise NotReady('Waiting for NX2navi')
                self.next_attach = now + 2
                self.game = Game.find(self.executable)
                if not self.game:
                    raise NotReady('Waiting for NX2navi')
                self.had_game = True
            manager, area, xyz = self.game.state()
            selected = [name for name, var in self.enabled.items() if var.get() and
                        ((self.link_auto.get() or self.link_once) if name in ('health', 'magic')
                         else (self.auto.get() or self.once))]
            resources = self.game.resources(manager, selected)
            round_ammo = [name for name, var in self.minigame_enabled.items() if var.get()] if self.minigames.get() else ()
            minigame = self.game.minigame_resources(manager, round_ammo)
            self.minigame_text.set(f"Minigame {minigame['resource']}: {minigame['current']}/{minigame['capacity']}"
                                   if minigame else 'Minigame ammo: waiting for a round')
            self.once = False
            self.link_once = False
            ids, flags = self.game.collections(manager, self.named)
            progress = SimpleNamespace(ids=ids, values=flags)
            active = [x for x in self.catalog if (self.skulls.get() if x['kind'] == 'skull' else self.hearts.get())]
            rows = nearby(active, area, xyz, progress)
            self.area.set(area.replace('_', ' '))
            done = {kind: len({x['id'] for x in self.catalog if x['kind'] == kind and collected(x, progress)})
                    for kind in ('skull', 'heart')}
            self.counts.set(f"Found {done['skull']}/100 skulls   |   {done['heart']}/36 heart locations")
            for name, row in resources.items():
                title = name.replace('_', ' ').title()
                label = f"{title}: {row['current']}/{row['capacity']}" if row['unlocked'] else f'{title}: locked'
                if row['unlocked'] and name == 'health':
                    label = f"Health: {row['current'] / 4:g}/{row['capacity'] / 4:g} hearts"
                elif row['unlocked'] and name == 'magic':
                    label = f"Magic: {row['current'] * 100 / row['capacity']:.0f}%"
                self.resource_text[name].set(label)
            self.last_rows = rows
            near = [x for x in rows if x['distance'] <= self.alert_radius.get()]
            keys = {(area, x['id']) for x in near}
            if near:
                target = near[0]
                kind = 'GOLD SKULLTULA' if target['kind'] == 'skull' else 'HEART PIECE'
                self.alert.set(f"{kind} NEARBY - {target['distance']:.0f} m\nHeight difference: {target['dy']:+.0f} m")
                if keys - self.last_near and self.sound.get() and now - self.last_sound >= 4:
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    self.last_sound = now
                    logging.info('Proximity alert: %s in %s, %.1f m', kind, area, target['distance'])
            elif rows:
                self.alert.set(f"Nearest missing {rows[0]['kind']}: {rows[0]['distance']:.0f} m")
            else:
                self.alert.set('No missing collectibles mapped in this area')
            self.last_near = keys
            self.status.set('Live collection tracking. Refill caps follow upgrades.\nA nearby marker may require night-time, equipment or another floor.')
            if now >= self.next_record:
                self.next_record = now + 3
                state = dict(utc=datetime.now(timezone.utc).isoformat(), pid=self.game.pid, area=area,
                             xyz=xyz, resources=resources, minigame=minigame, timer=self.timer_state,
                             timer_freeze_enabled=self.freeze_timer.get(), found=done,
                             nearest=rows[:5], refills_enabled=self.auto.get(),
                             link_refills_enabled=self.link_auto.get(), run_speed_2x=self.run_speed.get(),
                             roll_speed_2x=self.roll_speed.get(),
                             invisible_to_enemies=self.invisible.get(),
                             jump_height_2x=self.jump_height.get(),
                             dive_mode=self.dive_mode.get(),
                             orientation='camera-up', camera_forward=self.game.camera_direction(),
                             radar_hidden=self.hidden, hotkey_registered=self.hotkey is not None)
                (self.data_dir / 'live-status.local.json').write_text(json.dumps(state, indent=2))
        except NotReady as error:
            self.last_rows = []
            self.status.set(str(error))
            self.alert.set('Waiting for active gameplay')
            self.last_near = set()
        except (OSError, ValueError) as error:
            self.auto.set(False)
            self.link_auto.set(False)
            self.minigames.set(False)
            self.once = False
            self.link_once = False
            logging.exception('Helper paused')
            self.status.set(f'Paused; refills stopped: {error}')
        self.root.after(250, self.tick)

    def refresh_player(self):
        if self.stopped:
            return
        try:
            if not self.game or not self.game.alive():
                raise NotReady('Waiting for NX2navi')
            self.game.state()
            self.run_modifier.update(self.game, self.run_speed.get())
            self.player_modifiers.update(self.game, self.run_speed.get(), self.jump_height.get(), self.roll_speed.get())
            modes = [name for enabled, name in ((self.run_speed.get(), 'Run / swim 2x'),
                                               (self.roll_speed.get(), 'Roll 2x'),
                                               (self.jump_height.get(), 'Jump 2x')) if enabled]
            self.movement_text.set(' / '.join(modes) if modes else 'Movement: normal')
        except NotReady as error:
            self.movement_text.set(f'Movement paused: {error}')
        except (OSError, ValueError) as error:
            self.run_speed.set(False)
            self.roll_speed.set(False)
            self.jump_height.set(False)
            logging.exception('Movement controls stopped')
            self.movement_text.set(f'Movement stopped: {error}')
        self.root.after(100, self.refresh_player)

    def refresh_diving(self):
        if self.stopped:
            return
        try:
            if not self.game or not self.game.alive():
                raise NotReady('Waiting for NX2navi')
            self.game.state()
            result = self.dive_limit.update(self.game, self.dive_mode.get())
            if result:
                text = ('Unlimited depth' if result['mode'] == 'Unlimited'
                        else f"Dive depth: {result['depth']:g} m (normal {result['base']:g} m)")
            else:
                text = ('Dive limit: normal scale depth' if self.dive_mode.get() == 'Off'
                        else 'Ready for your next dive')
            self.dive_text.set(text)
        except NotReady as error:
            self.dive_text.set(f'Dive control paused: {error}')
        except (OSError, ValueError) as error:
            self.dive_mode.set('Off')
            logging.exception('Dive controls stopped')
            self.dive_text.set(f'Dive control stopped: {error}')
        self.root.after(25 if self.dive_mode.get() != 'Off' else 250, self.refresh_diving)

    def refresh_stealth(self):
        if self.stopped:
            return
        try:
            if not self.game or not self.game.alive():
                raise NotReady('Waiting for NX2navi')
            self.invisible_text.set(self.enemy_stealth.update(self.game, self.invisible.get()))
        except NotReady as error:
            self.invisible_text.set(f'Enemy stealth: {error}')
        except (OSError, ValueError) as error:
            self.invisible.set(False)
            logging.exception('Enemy stealth stopped')
            self.invisible_text.set(f'Enemy stealth stopped: {error}')
        self.root.after(100, self.refresh_stealth)

    def retry_close(self):
        self.close_job = None
        self.close()

    def close(self):
        if self.close_job is not None:
            return
        self.stopped = True
        self.closing = True
        self.invisible.set(False)
        if self.game and self.game.alive():
            errors = []
            for control in (self.run_modifier, self.player_modifiers, self.dive_limit):
                try:
                    control.restore(self.game)
                except (NotReady, OSError, ValueError) as error:
                    logging.exception('Could not restore Link settings')
                    errors.append(str(error))
            try:
                self.enemy_stealth.restore(self.game)
            except NotReady as error:
                self.status.set(f'Finishing trainer cleanup: {error}.')
                self.root.deiconify()
                self.close_job = self.root.after(100, self.retry_close)
                return
            except (OSError, ValueError) as error:
                logging.exception('Could not restore enemy stealth')
                errors.append(str(error))
            if errors:
                self.run_speed.set(False)
                self.roll_speed.set(False)
                self.jump_height.set(False)
                self.dive_mode.set('Off')
                messagebox.showwarning('Navi Scout', f"Some Link settings could not be restored: {'; '.join(errors)}\n"
                                       'Restart NX2navi to clear remaining overrides.', parent=self.root)
        self.save_preferences()
        if self.hotkey:
            self.hotkey.close()
        if self.game:
            self.game.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description='Navi Scout standalone companion')
    parser.add_argument('--launch', action='store_true', help='Launch the configured game if necessary')
    parser.add_argument('--attach-only', action='store_true', help='Wait for the game instead of launching it')
    parser.add_argument('--setup', action='store_true', help='Choose or reconnect your game installation')
    parser.add_argument('--demo', action='store_true', help='Show labeled sample data without attaching to a game')
    parser.add_argument('--self-test-report', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--check-game', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--report', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_test_report:
        import zstandard
        probe = tk.Tk()
        probe.withdraw()
        patchlevel = probe.tk.call('info', 'patchlevel')
        probe.destroy()
        atomic_json(args.self_test_report, dict(version=VERSION, tkinter=str(patchlevel),
                                               zstandard=zstandard.__version__, frozen=bool(getattr(sys, 'frozen', False))))
        return
    if args.check_game:
        from catalog import extract_catalog
        game = validate_game(args.check_game)
        catalog = extract_catalog(game)
        if not args.report:
            parser.error('--check-game needs --report')
        atomic_json(args.report, dict(game_build=catalog['game_build'], unique=catalog['unique'],
                                      entries=len(catalog['items']), game_files_modified=False))
        return
    if args.demo:
        app = Companion(Path.cwd(), Path(tempfile.mkdtemp(prefix='NaviScout-preview-')), demo=True)
        app.root.mainloop()
        return
    data = user_data()
    data.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=data / 'companion.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    from first_run import configure
    try:
        game = configure(data, force=args.setup)
        if game is None:
            return
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
        kernel.CreateMutexW.restype = W.HANDLE
        mutex = kernel.CreateMutexW(None, False, 'Local\\NaviScout-NX2navi-Desktop')
        if not mutex:
            raise C.WinError(C.get_last_error())
        if C.get_last_error() == 183:
            kernel.CloseHandle.argtypes = [W.HANDLE]
            kernel.CloseHandle(mutex)
            notice = tk.Tk()
            notice.withdraw()
            messagebox.showinfo('Navi Scout', 'Navi Scout is already running. Press F8 to show it.', parent=notice)
            notice.destroy()
            return
        try:
            app = Companion(game, data, launch=not args.attach_only)
            app.root.mainloop()
        finally:
            kernel.CloseHandle.argtypes = [W.HANDLE]
            kernel.CloseHandle(mutex)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        logging.exception('Navi Scout could not start')
        notice = tk.Tk()
        notice.withdraw()
        messagebox.showerror('Navi Scout could not start', str(error), parent=notice)
        notice.destroy()


if __name__ == '__main__':
    main()
