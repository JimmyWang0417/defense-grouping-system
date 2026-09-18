import flet as ft


def build_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=ft.Colors.BLUE_700,
            secondary=ft.Colors.TEAL_600,
            error=ft.Colors.RED_600,
        ),
        use_material3=True,
        font_family="Noto Sans CJK SC",
    )
