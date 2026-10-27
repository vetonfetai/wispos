#!/usr/bin/env python3
"""Generates the extra Wisp wallpapers (SVG). night.svg is hand-made."""
TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{bg0}"/><stop offset=".55" stop-color="{bg1}"/><stop offset="1" stop-color="{bg2}"/>
    </linearGradient>
    <radialGradient id="ga" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="{c1}" stop-opacity="{glow}"/><stop offset="1" stop-color="{c1}" stop-opacity="0"/></radialGradient>
    <radialGradient id="gb" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="{c2}" stop-opacity="{glow}"/><stop offset="1" stop-color="{c2}" stop-opacity="0"/></radialGradient>
    <linearGradient id="w" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{c1}" stop-opacity="0"/><stop offset=".45" stop-color="{c1}" stop-opacity=".95"/><stop offset="1" stop-color="{c2}" stop-opacity="0"/>
    </linearGradient>
    <filter id="blur" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="{blur}"/></filter>
    <filter id="soft" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="1.2"/></filter>
  </defs>
  <rect width="1920" height="1080" fill="url(#bg)"/>
  <ellipse cx="{ax}" cy="{ay}" rx="680" ry="440" fill="url(#gb)" opacity=".6"/>
  <ellipse cx="{bx}" cy="{by}" rx="720" ry="400" fill="url(#ga)" opacity=".45"/>
  <g fill="none" stroke="url(#w)" stroke-linecap="round">
    <path d="{p1}" stroke-width="12" filter="url(#blur)" opacity=".7"/>
    <path d="{p1}" stroke-width="2.2" filter="url(#soft)"/>
    <path d="{p2}" stroke-width="1.4" opacity=".55"/>
    <path d="{p3}" stroke-width="1" opacity=".35"/>
  </g>
</svg>
"""
WAVES = {
    "rise": ("M-40 820 C 420 760, 760 520, 1100 600 S 1640 300, 1980 260",
             "M-40 880 C 460 820, 800 600, 1140 670 S 1660 380, 1980 350",
             "M-40 760 C 380 700, 720 450, 1060 530 S 1620 220, 1980 170"),
    "flow": ("M-40 600 C 320 460, 720 760, 1060 560 S 1600 640, 1980 420",
             "M-40 660 C 360 520, 760 820, 1100 620 S 1620 700, 1980 500",
             "M-40 540 C 280 400, 680 700, 1020 500 S 1580 580, 1980 340"),
    "fall": ("M-40 300 C 420 360, 700 700, 1080 640 S 1620 860, 1980 820",
             "M-40 360 C 460 420, 740 760, 1120 700 S 1640 920, 1980 900",
             "M-40 240 C 380 300, 660 640, 1040 580 S 1600 800, 1980 740"),
}
MOODS = {
    "aurora": dict(bg0="#06100f", bg1="#0b1a1d", bg2="#0d1426", c1="#5ee6b8", c2="#7aa8ff", glow=".5", blur=7, ax=1420, ay=380, bx=480, by=780, wave="rise"),
    "ember": dict(bg0="#120a0d", bg1="#1b0f16", bg2="#24101a", c1="#ff9a6b", c2="#ff6f9e", glow=".5", blur=7, ax=1350, ay=420, bx=560, by=760, wave="flow"),
    "lagoon": dict(bg0="#071019", bg1="#0a1828", bg2="#0e1636", c1="#5fd4ff", c2="#8a7dff", glow=".5", blur=7, ax=520, ay=360, bx=1400, by=780, wave="fall"),
    "dawn": dict(bg0="#eef1f8", bg1="#e4e8f4", bg2="#efe6f5", c1="#5b8cff", c2="#a97bff", glow=".35", blur=6, ax=1380, ay=400, bx=520, by=760, wave="flow"),
}
for name, m in MOODS.items():
    p1, p2, p3 = WAVES[m.pop("wave")]
    with open(f"wallpapers/{name}.svg", "w") as f:
        f.write(TEMPLATE.format(p1=p1, p2=p2, p3=p3, **m))
print("ok")
