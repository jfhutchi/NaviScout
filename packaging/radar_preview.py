"""A clearly labeled screenshot fixture using Navi Scout's actual renderer."""
import tkinter as tk
from types import SimpleNamespace

from companion import Companion, BG, PANEL, TEXT

root = tk.Tk()
root.title('Navi Scout - Sample radar bearings')
root.configure(bg=BG)
root.attributes('-topmost', True)
for index, (kind, dx, dz, forward, title) in enumerate([
        ('skull', 200, 0, (0, -1), 'SAMPLE: outside range, east'),
        ('heart', 200, 0, (1, 0), 'SAMPLE: camera now faces east'),
        ('skull', 30, -40, (0, -1), 'SAMPLE: target inside range')]):
    frame = tk.Frame(root, bg=BG)
    frame.grid(row=0, column=index)
    tk.Label(frame, text=title, bg=BG, fg=TEXT).pack(pady=7)
    canvas = tk.Canvas(frame, width=340, height=260, bg=PANEL, highlightthickness=0)
    canvas.pack(padx=6, pady=6)
    view = SimpleNamespace(canvas=canvas, range=tk.IntVar(value=100))
    Companion.draw(view, [dict(kind=kind, dx=dx, dz=dz, dy=0,
                              distance=(dx * dx + dz * dz) ** 0.5)], forward)
tk.Label(root, text='Illustrative samples rendered by Navi Scout. No game is attached.',
         bg=BG, fg=TEXT).grid(row=1, column=0, columnspan=3, pady=9)
root.mainloop()
