"""Design tokens из design/pos_cashier.pen.variables. Источник правды по UI."""

# Brand warm amber-orange из соседнего проекта restos
# (app/globals.css → --primary: oklch(0.62 0.16 45)). Совпадает с CSS-цветом
# `chocolate`. Был #F97316 (Tailwind orange-500) — слишком яркий, заменён.
COLORS = {
    "accent_orange": "#D2691E",
    "accent_orange_pressed": "#A85010",
    "bg_dark": "#0F172A",
    "bg_gray": "#F1F5F9",
    "bg_light": "#F5F7FA",
    "bg_white": "#FFFFFF",
    "border_light": "#E2E8F0",
    "danger_red": "#DC2626",
    "primary_blue": "#2563EB",
    "success_green": "#16A34A",
    "text_primary": "#1E293B",
    "text_secondary": "#64748B",
    "text_white": "#FFFFFF",
    "warning_yellow": "#FBBF24",
}

FONT_SIZE = {
    "sm": 12,
    "base": 14,
    "btn": 16,
    "heading": 24,
    "title": 28,
    "amount": 32,
}

RADIUS = {"sm": 8, "md": 12, "lg": 16}
SPACING = {"sm": 8, "md": 12, "lg": 16, "xl": 24}

FONT_FAMILY = "Inter, -apple-system, Segoe UI, sans-serif"
