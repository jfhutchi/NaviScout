"""Original vector illustrations for the trainer's item controls."""
import tkinter as tk


class ItemIcon(tk.Canvas):
    def __init__(self, parent, name, size=24):
        names = ('rupees', 'sticks', 'seeds', 'nuts', 'bombs', 'bombchus', 'arrows',
                 'magic_beans', 'scrub_seeds', 'health', 'magic')
        if name not in names:
            raise ValueError(f'Unknown item icon: {name}')
        super().__init__(parent, width=size, height=size, bg=parent.cget('bg'),
                         highlightthickness=0, takefocus=0)
        edge, cream = '#3c2a1b', '#fff1c5'
        if name == 'rupees':
            self.create_polygon(12, 1, 21, 7, 20, 17, 12, 23, 4, 17, 3, 7,
                                fill='#69cd83', outline='#c9f3ab')
            self.create_polygon(12, 4, 16, 8, 16, 16, 12, 20, 8, 16, 8, 8,
                                fill='#248e68', outline='')
            self.create_line(12, 4, 12, 20, fill='#c9f3ab')
        elif name == 'sticks':
            self.create_line(5, 21, 16, 4, fill=edge, width=6)
            self.create_line(5, 21, 16, 4, fill='#c59355', width=4)
            self.create_line(11, 12, 20, 10, fill='#c59355', width=3)
            self.create_line(9, 16, 5, 9, fill='#aa713d', width=3)
            self.create_oval(13, 1, 18, 6, fill='#dfbd7a', outline=edge)
        elif name in ('seeds', 'scrub_seeds'):
            self.create_polygon(6, 8, 17, 8, 21, 18, 18, 22, 5, 22, 2, 18,
                                fill='#ae7946' if name == 'seeds' else '#718d4a', outline='#e6c080')
            self.create_polygon(7, 3, 16, 3, 14, 8, 9, 8, fill='#d4aa6a', outline=edge)
            self.create_line(6, 8, 18, 8, fill='#f1d88c', width=2)
            self.create_oval(8, 12, 15, 18, fill='#f2c774', outline=edge)
            if name == 'scrub_seeds':
                self.create_polygon(13, 13, 18, 10, 18, 14, fill='#bce17d', outline='')
        elif name == 'nuts':
            self.create_oval(5, 6, 20, 21, fill='#bf834a', outline='#f3c782')
            self.create_arc(6, 6, 19, 21, start=95, extent=180, style='arc', outline='#e8b568', width=2)
            self.create_polygon(4, 10, 7, 5, 17, 4, 21, 9, 17, 12, 8, 12,
                                fill='#775033', outline='#d3a363')
            self.create_line(12, 5, 14, 1, fill='#d3a363', width=2)
        elif name == 'bombs':
            self.create_line(13, 6, 16, 3, 20, 5, fill='#d6b478', width=2)
            self.create_oval(3, 7, 21, 23, fill='#4467a2', outline='#b0cbe9')
            self.create_oval(6, 10, 11, 14, fill='#94b5da', outline='')
            self.create_rectangle(10, 5, 15, 9, fill='#c6ac71', outline=edge)
            self.create_line(20, 1, 20, 7, fill='#f8d17c')
            self.create_line(17, 4, 23, 4, fill='#ffad56')
        elif name == 'bombchus':
            self.create_oval(2, 10, 20, 21, fill='#577bb6', outline='#c0d9f0')
            self.create_polygon(16, 10, 23, 15, 18, 19, fill='#96b6d7', outline='#c0d9f0')
            self.create_oval(8, 5, 14, 12, fill='#7799c4', outline='#c0d9f0')
            self.create_oval(17, 12, 19, 14, fill='#e96565', outline='')
            self.create_line(4, 20, 4, 23, 10, 23, fill='#e4c476', width=2)
            self.create_line(14, 20, 14, 23, 20, 23, fill='#e4c476', width=2)
            self.create_line(3, 12, 1, 7, 4, 3, fill='#e4c476', width=2)
        elif name == 'arrows':
            for offset in (-3, 3):
                self.create_line(5 + offset, 21, 17 + offset, 4, fill='#d7ad72', width=2)
                self.create_polygon(17 + offset, 2, 13 + offset, 8, 19 + offset, 6,
                                    fill='#cbdde2', outline='#718d9b')
                self.create_line(5 + offset, 20, 2 + offset, 16, fill=cream, width=2)
        elif name == 'magic_beans':
            self.create_oval(3, 5, 20, 21, fill='#7da557', outline='#d0e59a')
            self.create_oval(10, 2, 22, 15, fill='#96ba63', outline='#d0e59a')
            self.create_line(8, 17, 12, 14, 13, 8, smooth=True, fill='#dbeaac', width=2)
            self.create_line(15, 4, 18, 1, fill='#b9d580', width=2)
        elif name == 'health':
            self.create_polygon(12, 23, 2, 13, 1, 7, 5, 2, 10, 3, 12, 6,
                                14, 3, 19, 2, 23, 7, 22, 13,
                                fill='#d86a7b', outline='#ffd7cb', smooth=True)
            self.create_arc(4, 5, 12, 14, start=55, extent=110, style='arc', outline='#ffe4ce', width=2)
        elif name == 'magic':
            self.create_polygon(7, 7, 17, 7, 21, 19, 18, 23, 6, 23, 3, 19,
                                fill='#accbbb', outline='#e2f1d1')
            self.create_polygon(7, 12, 17, 12, 19, 20, 6, 20,
                                fill='#66b887', outline='')
            self.create_rectangle(8, 2, 16, 7, fill='#c8985b', outline=cream)
            self.create_line(7, 10, 6, 17, fill='#eff8df', width=2)
        if size != 24:
            self.scale('all', 0, 0, size / 24, size / 24)
