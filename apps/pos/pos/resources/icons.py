"""Lucide icon SVG inline + helpers `qicon(name, color, size)`.

Lucide v0.x icons (ISC license). Используем минимальный набор для UI кассира.
SVG у lucide все 24×24, stroke='currentColor', round caps. Подменяем
currentColor на нужный (helper рендерит в QPixmap)."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Каждый SVG — строка без xmlns/префиксов, рендерится QSvgRenderer.
# stroke="currentColor" заменяется на нужный цвет в _render().
ICONS: dict[str, str] = {
    "layout-grid": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect width="7" height="7" x="3" y="3" rx="1"/>'
        '<rect width="7" height="7" x="14" y="3" rx="1"/>'
        '<rect width="7" height="7" x="14" y="14" rx="1"/>'
        '<rect width="7" height="7" x="3" y="14" rx="1"/>'
        '</svg>'
    ),
    "utensils": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/>'
        '<path d="M7 2v20"/>'
        '<path d="M21 15V2v0a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>'
        '</svg>'
    ),
    "receipt": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/>'
        '<path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/>'
        '<path d="M12 17.5v-11"/>'
        '</svg>'
    ),
    "settings": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>'
        '<circle cx="12" cy="12" r="3"/>'
        '</svg>'
    ),
    "log-out": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
        '<polyline points="16 17 21 12 16 7"/>'
        '<line x1="21" x2="9" y1="12" y2="12"/>'
        '</svg>'
    ),
    "search": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="11" cy="11" r="8"/>'
        '<path d="m21 21-4.3-4.3"/>'
        '</svg>'
    ),
    "x": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'
        '</svg>'
    ),
    "check": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="20 6 9 17 4 12"/>'
        '</svg>'
    ),
    "alert-triangle": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>'
        '<path d="M12 9v4"/><path d="M12 17h.01"/>'
        '</svg>'
    ),
    "refresh-cw": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>'
        '<path d="M21 3v5h-5"/>'
        '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>'
        '<path d="M3 21v-5h5"/>'
        '</svg>'
    ),
    "plus": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M5 12h14"/><path d="M12 5v14"/>'
        '</svg>'
    ),
    "more-horizontal": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="1"/>'
        '<circle cx="19" cy="12" r="1"/>'
        '<circle cx="5" cy="12" r="1"/>'
        '</svg>'
    ),
    "chevron-down": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m6 9 6 6 6-6"/>'
        '</svg>'
    ),
    "arrow-right": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>'
        '</svg>'
    ),
    "arrow-left": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>'
        '</svg>'
    ),
    "printer": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="6 9 6 2 18 2 18 9"/>'
        '<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>'
        '<rect width="12" height="8" x="6" y="14"/>'
        '</svg>'
    ),
    "combine": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M10 18H5a3 3 0 0 1-3-3v-1"/>'
        '<path d="M14 2a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2"/>'
        '<path d="M20 2a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2"/>'
        '<path d="m7 21 3-3-3-3"/>'
        '<rect x="14" y="14" width="8" height="8" rx="2"/>'
        '</svg>'
    ),
    # ----- категории меню (lucide) -----
    "salad": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M7 21h10"/>'
        '<path d="M5 21a16 16 0 0 1-3.8-7.8 2 2 0 0 1 2.8-2.4l1.4.7a2 2 0 0 0 2.4-.4l3.4-3.4 4.2 4.2-3.4 3.4a2 2 0 0 0-.4 2.4l.7 1.4a2 2 0 0 1-2.4 2.8A16 16 0 0 1 5 21Z"/>'
        '<path d="M14 4.5C13 6.4 12 8 12 11"/><path d="M19.5 9.5 22 12"/>'
        '</svg>'
    ),
    "soup": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 21a9 9 0 0 0 9-9H3a9 9 0 0 0 9 9Z"/><path d="M7 21h10"/>'
        '<path d="M19.5 12 22 6"/>'
        '<path d="M16.25 3c.27.1.8.53.75 1.36-.06.83-.93 1.2-1 2.02-.05.78.34 1.24.73 1.62"/>'
        '<path d="M11.25 3c.27.1.8.53.74 1.36-.05.83-.93 1.2-.98 2.02-.06.78.34 1.24.72 1.62"/>'
        '<path d="M6.25 3c.27.1.8.53.75 1.36-.06.83-.93 1.2-1 2.02-.05.78.34 1.24.74 1.62"/>'
        '</svg>'
    ),
    "flame": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>'
        '</svg>'
    ),
    "cup-soda": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m6 8 1.75 12.28a2 2 0 0 0 2 1.72h4.54a2 2 0 0 0 2-1.72L18 8"/>'
        '<path d="M5 8h14"/><path d="M7 15a6.47 6.47 0 0 1 5 0 6.47 6.47 0 0 0 5 0"/>'
        '<path d="m12 8 1-6h2"/>'
        '</svg>'
    ),
    "cake-slice": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="9" cy="7" r="2"/>'
        '<path d="M7.2 7.9 3 11v9a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9.8L14 4"/>'
        '<path d="M3 11h18"/><path d="m17 14-3 3 1.5 1.5L17 17"/>'
        '</svg>'
    ),
    "croissant": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m4.6 13.11 5.79-3.21c1.89-1.05 4.79 1.78 3.71 3.71l-3.22 5.81C8.8 23.16.79 15.23 4.6 13.11Z"/>'
        '<path d="m10.5 9.5-1-2.29C9.2 6.48 8.8 6 8 6H4.5C2.79 6 2 6.5 2 8.5a7.71 7.71 0 0 0 2 4.83"/>'
        '<path d="M8 6c0-1.55.24-4-2-4-2 0-2.5 2.17-2.5 4"/>'
        '<path d="m14.5 13.5 2.29 1c.73.3 1.21.7 1.21 1.5v3.5c0 1.71-.5 2.5-2.5 2.5a7.71 7.71 0 0 1-4.83-2"/>'
        '<path d="M18 16c1.55 0 4-.24 4 2 0 2-2.17 2.5-4 2.5"/>'
        '</svg>'
    ),
    "beef": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12.5" cy="8.5" r="2.5"/>'
        '<path d="M12.5 2a6.5 6.5 0 0 0-6.22 4.6c-1.1 3.13-.78 3.9-3.18 6.08A3 3 0 0 0 5 18c4 0 8.4-1.8 11.4-4.3A6.5 6.5 0 0 0 12.5 2Z"/>'
        '<path d="m18.5 6 2.19 4.5a6.48 6.48 0 0 1 .31 2 6.49 6.49 0 0 1-2.6 5.2C15.4 20.2 11 22 7 22a3 3 0 0 1-2.68-4.34l.34-.66"/>'
        '</svg>'
    ),
    "wheat": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M2 22 16 8"/>'
        '<path d="M3.47 12.53 5 11l1.53 1.53a3.5 3.5 0 0 1 0 4.94L5 19l-1.53-1.53a3.5 3.5 0 0 1 0-4.94Z"/>'
        '<path d="M7.47 8.53 9 7l1.53 1.53a3.5 3.5 0 0 1 0 4.94L9 15l-1.53-1.53a3.5 3.5 0 0 1 0-4.94Z"/>'
        '<path d="M11.47 4.53 13 3l1.53 1.53a3.5 3.5 0 0 1 0 4.94L13 11l-1.53-1.53a3.5 3.5 0 0 1 0-4.94Z"/>'
        '<path d="M20 2h2v2a4 4 0 0 1-4 4h-2V6a4 4 0 0 1 4-4Z"/>'
        '<path d="M11.47 17.47 13 19l-1.53 1.53a3.5 3.5 0 0 1-4.94 0L5 19l1.53-1.53a3.5 3.5 0 0 1 4.94 0Z"/>'
        '<path d="M15.47 13.47 17 15l-1.53 1.53a3.5 3.5 0 0 1-4.94 0L9 15l1.53-1.53a3.5 3.5 0 0 1 4.94 0Z"/>'
        '<path d="M19.47 9.47 21 11l-1.53 1.53a3.5 3.5 0 0 1-4.94 0L13 11l1.53-1.53a3.5 3.5 0 0 1 4.94 0Z"/>'
        '</svg>'
    ),
    "utensils-crossed": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m16 2-2.3 2.3a3 3 0 0 0 0 4.2l1.8 1.8a3 3 0 0 0 4.2 0L22 8"/>'
        '<path d="M15 15 3.3 3.3a4.2 4.2 0 0 0 0 6l7.3 7.3c.7.7 2 .7 2.8 0L15 15Zm0 0 7 7"/>'
        '<path d="m2.1 21.8 6.4-6.3"/><path d="m19 5-7 7"/>'
        '</svg>'
    ),
    "drumstick": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M15.45 15.4c-2.13.65-4.3.32-5.7-1.1-2.29-2.27-1.76-6.5 1.17-9.42 2.93-2.93 7.15-3.46 9.43-1.18 1.41 1.41 1.74 3.57 1.1 5.71-1.4-.51-3.26-.02-4.64 1.36-1.38 1.38-1.87 3.23-1.36 4.63z"/>'
        '<path d="m11.25 15.6-2.16 2.16a2.5 2.5 0 1 1-4.56 1.73 2.49 2.49 0 0 1-1.41-4.24 2.5 2.5 0 0 1 3.14-.32l2.16-2.16"/>'
        '</svg>'
    ),
    "egg-fried": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="11.5" cy="12.5" r="3.5"/>'
        '<path d="M3 8a5 5 0 0 1 8.4-3.6 5 5 0 0 1 8 6 5 5 0 0 1 1.2 7.8 5 5 0 0 1-7 1.8A5 5 0 0 1 6.4 22 5 5 0 0 1 .8 13.4 5 5 0 0 1 3 8Z"/>'
        '</svg>'
    ),
    "pizza": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M15 11h.01"/><path d="M11 15h.01"/><path d="M16 16h.01"/>'
        '<path d="m2 16 20 6-6-20A20 20 0 0 0 2 16"/>'
        '<path d="M5.71 17.11a17.04 17.04 0 0 1 11.4-11.4"/>'
        '</svg>'
    ),
    "sunrise": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 2v8"/><path d="m4.93 10.93 1.41 1.41"/>'
        '<path d="M2 18h2"/><path d="M20 18h2"/>'
        '<path d="m19.07 10.93-1.41 1.41"/><path d="M22 22H2"/>'
        '<path d="m8 6 4-4 4 4"/><path d="M16 18a4 4 0 0 0-8 0"/>'
        '</svg>'
    ),
    "package": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M16.5 9.4 7.5 4.21"/>'
        '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>'
        '<polyline points="3.27 6.96 12 12.01 20.73 6.96"/>'
        '<line x1="12" x2="12" y1="22.08" y2="12"/>'
        '</svg>'
    ),
    "baby": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M9 12h.01"/><path d="M15 12h.01"/>'
        '<path d="M10 16c.5.3 1.2.5 2 .5s1.5-.2 2-.5"/>'
        '<path d="M19 6.3a9 9 0 0 1 1.8 3.9 2 2 0 0 1 0 3.6 9 9 0 0 1-17.6 0 2 2 0 0 1 0-3.6A9 9 0 0 1 12 3c2 0 3.5 1.1 3.5 2.5s-.9 2.5-2 2.5c-.8 0-1.5-.4-1.5-1"/>'
        '</svg>'
    ),
    "leaf": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19.2 2.96c1.4 6.85 6.4 12-3.2 17.04Z"/>'
        '<path d="M2 21c0-3 1.85-5.36 5.08-6"/>'
        '</svg>'
    ),
    "coffee": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M17 8h1a4 4 0 1 1 0 8h-1"/>'
        '<path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4Z"/>'
        '<line x1="6" x2="6" y1="2" y2="4"/>'
        '<line x1="10" x2="10" y1="2" y2="4"/>'
        '<line x1="14" x2="14" y1="2" y2="4"/>'
        '</svg>'
    ),
    "banknote": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect width="20" height="12" x="2" y="6" rx="2"/>'
        '<circle cx="12" cy="12" r="2"/>'
        '<path d="M6 12h.01M18 12h.01"/>'
        '</svg>'
    ),
    "glass-water": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M15.2 22H8.8a2 2 0 0 1-2-1.79L5 3h14l-1.81 17.21A2 2 0 0 1 15.2 22Z"/>'
        '<path d="M6 12a5 5 0 0 1 6 0 5 5 0 0 0 6 0"/>'
        '</svg>'
    ),
    "droplets": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M7 16.3c2.2 0 4-1.83 4-4.05 0-1.16-.57-2.26-1.71-3.19S7.29 6.75 7 5.3c-.29 1.45-1.14 2.84-2.29 3.76S3 11.1 3 12.25c0 2.22 1.8 4.05 4 4.05z"/>'
        '<path d="M12.56 6.6A10.97 10.97 0 0 0 14 3.02c.5 2.5 2 4.9 4 6.5s3 3.5 3 5.5a6.98 6.98 0 0 1-11.91 4.97"/>'
        '</svg>'
    ),
    "credit-card": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect width="20" height="14" x="2" y="5" rx="2"/>'
        '<line x1="2" x2="22" y1="10" y2="10"/>'
        '</svg>'
    ),
    "qr-code": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect width="5" height="5" x="3" y="3" rx="1"/>'
        '<rect width="5" height="5" x="16" y="3" rx="1"/>'
        '<rect width="5" height="5" x="3" y="16" rx="1"/>'
        '<path d="M21 16h-3a2 2 0 0 0-2 2v3"/>'
        '<path d="M21 21v.01"/>'
        '<path d="M12 7v3a2 2 0 0 1-2 2H7"/>'
        '<path d="M3 12h.01"/>'
        '<path d="M12 3h.01"/>'
        '<path d="M12 16v.01"/>'
        '<path d="M16 12h1"/>'
        '<path d="M21 12v.01"/>'
        '<path d="M12 21v-1"/>'
        '</svg>'
    ),
    "smartphone": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"/>'
        '<path d="M12 18h.01"/>'
        '</svg>'
    ),
    "banknote": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect width="20" height="12" x="2" y="6" rx="2"/>'
        '<circle cx="12" cy="12" r="2"/>'
        '<path d="M6 12h.01M18 12h.01"/>'
        '</svg>'
    ),
    "percent": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<line x1="19" x2="5" y1="5" y2="19"/>'
        '<circle cx="6.5" cy="6.5" r="2.5"/>'
        '<circle cx="17.5" cy="17.5" r="2.5"/>'
        '</svg>'
    ),
    "hand-coins": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M11 15h2a2 2 0 1 0 0-4h-3c-.6 0-1.1.2-1.4.6L3 17"/>'
        '<path d="m7 21 1.6-1.4c.3-.4.8-.6 1.4-.6h4c1.1 0 2.1-.4 2.8-1.2l4.6-4.4a2 2 0 0 0-2.75-2.91l-4.2 3.9"/>'
        '<path d="m2 16 6 6"/>'
        '<circle cx="16" cy="9" r="2.9"/>'
        '<circle cx="6" cy="5" r="3"/>'
        '</svg>'
    ),
    "filter": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>'
        '</svg>'
    ),
    "edit-2": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>'
        '</svg>'
    ),
    "trash-2": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 6h18"/>'
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
        '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
        '<line x1="10" x2="10" y1="11" y2="17"/>'
        '<line x1="14" x2="14" y1="11" y2="17"/>'
        '</svg>'
    ),
    "wifi": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M5 13a10 10 0 0 1 14 0"/>'
        '<path d="M8.5 16.5a5 5 0 0 1 7 0"/>'
        '<path d="M2 8.82a15 15 0 0 1 20 0"/>'
        '<line x1="12" x2="12.01" y1="20" y2="20"/>'
        '</svg>'
    ),
    "wifi-off": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<line x1="2" x2="22" y1="2" y2="22"/>'
        '<path d="M8.5 16.5a5 5 0 0 1 7 0"/>'
        '<path d="M2 8.82a15 15 0 0 1 4.17-2.65"/>'
        '<path d="M10.66 5c4.01-.36 8.14.9 11.34 3.76"/>'
        '<path d="M16.85 11.25a10 10 0 0 1 2.22 1.68"/>'
        '<path d="M5 13a10 10 0 0 1 5.24-2.76"/>'
        '<line x1="12" x2="12.01" y1="20" y2="20"/>'
        '</svg>'
    ),
    "sandwich": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 11v3a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-3"/>'
        '<path d="M12 19H4a1 1 0 0 1-1-1v-2a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1h-3.83"/>'
        '<path d="m3 11 7.77-6.04a2 2 0 0 1 2.46 0L21 11H3Z"/>'
        '<path d="M12.97 19.77 7 15h12.5l-3.75 4.5a2 2 0 0 1-2.78.27Z"/>'
        '</svg>'
    ),
    "file-text": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M10 9H8"/>'
        '<path d="M16 13H8"/>'
        '<path d="M16 17H8"/>'
        '</svg>'
    ),
    "clipboard-check": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/>'
        '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>'
        '<path d="m9 14 2 2 4-4"/>'
        '</svg>'
    ),
    "history": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>'
        '<path d="M3 3v5h5"/>'
        '<path d="M12 7v5l4 2"/>'
        '</svg>'
    ),
}


def _render(svg_str: str, color: str, size: int) -> QPixmap:
    """Подменяет currentColor → color и рендерит SVG в QPixmap (с учётом DPR)."""
    body = svg_str.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(body.encode("utf-8")))
    pm = QPixmap(QSize(size, size))
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()
    return pm


def qicon(name: str, color: str = "#1E293B", size: int = 24) -> QIcon:
    """Возвращает QIcon с одним SVG-pixmap, перекрашенным в color.

    Для разных состояний (hover/disabled) вызови `qicon(name, color2)` отдельно
    и подставляй вручную в setIcon на сигналах — Qt без QIconEngine не делает
    автоматическую перекраску SVG."""
    if name not in ICONS:
        return QIcon()
    pm = _render(ICONS[name], color, size)
    icon = QIcon()
    icon.addPixmap(pm, QIcon.Normal, QIcon.On)
    icon.addPixmap(pm, QIcon.Normal, QIcon.Off)
    return icon


def qpixmap(name: str, color: str = "#1E293B", size: int = 24) -> QPixmap:
    """Прямой QPixmap для случаев когда нужен без QIcon (QLabel.setPixmap)."""
    if name not in ICONS:
        return QPixmap()
    return _render(ICONS[name], color, size)
