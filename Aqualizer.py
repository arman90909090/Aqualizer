# -*- coding: utf-8 -*-
"""
Aqualizer - Flet 1.1
Windows: UI and preset testing
Android: AudioEffect support when a valid audio session is supplied
"""

import asyncio
import json
import os
import random
import sys

import flet as ft


IS_ANDROID = hasattr(sys, "getandroidapilevel")

FREQUENCIES = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
BAND_LABELS = ["31", "62", "125", "250", "500",
               "1k", "2k", "4k", "8k", "16k"]

BUILTIN_PRESETS = {
    "Flat":       [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "Rock":       [5, 4, 3, 1, -1, -1, 1, 3, 4, 5],
    "Pop":        [-1, 0, 2, 4, 4, 2, 0, -1, -1, -1],
    "Jazz":       [3, 2, 1, 2, -1, -1, 0, 1, 2, 3],
    "Classical":  [4, 3, 2, 1, 0, 0, 1, 2, 3, 4],
    "Bass Boost": [9, 7, 5, 2, 0, 0, 0, 0, 0, 0],
    "Vocal":      [-2, -1, 0, 2, 5, 5, 3, 1, 0, -1],
    "Electronic": [5, 4, 1, 0, -2, 2, 1, 2, 4, 5],
}


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, float(value)))


# تنظیمات روی اندروید در فضای خصوصی و قابل‌نوشتن برنامه ذخیره می‌شوند.
# روی ویندوز، فایل تنظیمات کنار همین اسکریپت باقی می‌ماند.
CONFIG_DIR = (
    os.getenv("FLET_APP_STORAGE_DATA") or os.getcwd()
    if IS_ANDROID
    else os.path.dirname(os.path.abspath(__file__))
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "aqualizer_config.json")


def default_config():
    return {
        "gains": [0.0] * 10,
        "bass": 0.0,
        "stereo": 0.0,
        "enabled": True,
        "preset": "Flat",
        "custom_presets": {},
    }


def load_config():
    cfg = default_config()

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            saved = json.load(file)

        if not isinstance(saved, dict):
            return cfg

        gains = saved.get("gains")
        if isinstance(gains, list) and len(gains) == 10:
            cfg["gains"] = [clamp(v, -12, 12) for v in gains]

        cfg["bass"] = clamp(saved.get("bass", 0), 0, 100)

        # مهاجرت از نسخهٔ قبلی: virtual همان افکت 3D واقعی بود.
        cfg["stereo"] = clamp(
            saved.get("virtual", saved.get("stereo", 0)), 0, 100
        )

        cfg["enabled"] = bool(saved.get("enabled", True))

        old_custom = saved.get("custom_presets", {})
        if isinstance(old_custom, dict):
            for name, item in old_custom.items():
                if not isinstance(name, str) or not name.strip():
                    continue

                try:
                    if isinstance(item, list) and len(item) == 10:
                        # پریست‌های نسخهٔ قبلی فقط گین‌ها را داشتند.
                        snapshot = {
                            "gains": [clamp(v, -12, 12) for v in item],
                            "bass": 0.0,
                            "stereo": 0.0,
                        }
                    elif isinstance(item, dict):
                        values = item.get("gains")
                        if not isinstance(values, list) or len(values) != 10:
                            continue

                        snapshot = {
                            "gains": [clamp(v, -12, 12) for v in values],
                            "bass": clamp(item.get("bass", 0), 0, 100),
                            "stereo": clamp(
                                item.get("stereo", item.get("virtual", 0)),
                                0, 100,
                            ),
                        }
                    else:
                        continue

                    if name not in BUILTIN_PRESETS and name != "Custom":
                        cfg["custom_presets"][name] = snapshot
                except (TypeError, ValueError):
                    continue

        preset = saved.get("preset", "Flat")
        if preset in BUILTIN_PRESETS or preset in cfg["custom_presets"]:
            cfg["preset"] = preset
        else:
            cfg["preset"] = "Custom"

    except (OSError, TypeError, ValueError):
        pass

    return cfg


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(cfg, file, indent=2, ensure_ascii=False)
    except OSError as exc:
        print("Could not save configuration:", exc)


class AudioEngine:
    """
    این کلاس خودش نشست صوتی Samsung Music یا سایر برنامه‌ها را پیدا نمی‌کند.
    برای فعال‌شدن پردازش، باید attach_session با session ID معتبر فراخوانی شود.
    """

    def __init__(self):
        self.cfg = load_config()
        self.eq = None
        self.bass = None
        self.virtualizer = None
        self.session_id = None
        self.ready = False

    def release(self):
        for effect in (self.eq, self.bass, self.virtualizer):
            if effect is not None:
                try:
                    effect.release()
                except Exception as exc:
                    print("Audio effect release error:", exc)

        self.eq = None
        self.bass = None
        self.virtualizer = None
        self.session_id = None
        self.ready = False

    def attach_session(self, session_id):
        """برای اتصال بعدی به پلیر یا نشست صوتی قابل‌دسترسی."""
        if not IS_ANDROID:
            return False

        session_id = int(session_id)
        if session_id <= 0:
            raise ValueError("Audio session ID must be greater than zero.")

        self.release()

        try:
            from jnius import autoclass

            Equalizer = autoclass("android.media.audiofx.Equalizer")
            BassBoost = autoclass("android.media.audiofx.BassBoost")
            Virtualizer = autoclass("android.media.audiofx.Virtualizer")

            self.eq = Equalizer(0, session_id)
            self.bass = BassBoost(0, session_id)
            self.virtualizer = Virtualizer(0, session_id)

            self.session_id = session_id
            self.ready = True
            self.apply()
            return True

        except Exception as exc:
            print("Could not attach audio session:", exc)
            self.release()
            return False

    def apply(self):
        save_config(self.cfg)

        if not (IS_ANDROID and self.ready):
            return

        try:
            enabled = bool(self.cfg["enabled"])
            self.eq.setEnabled(enabled)

            bass_enabled = enabled and self.cfg["bass"] > 0
            stereo_enabled = enabled and self.cfg["stereo"] > 0

            self.bass.setEnabled(bass_enabled)
            self.virtualizer.setEnabled(stereo_enabled)

            if not enabled:
                return

            # تعداد و مرکز باندهای EQ روی گوشی‌های مختلف ممکن است
            # با ۱۰ باند نمایشی برنامه متفاوت باشد.
            band_range = self.eq.getBandLevelRange()

            for band in range(int(self.eq.getNumberOfBands())):
                center_hz = int(self.eq.getCenterFreq(band)) / 1000
                nearest = min(
                    range(10),
                    key=lambda i: abs(
                        __import__("math").log(
                            max(center_hz, 1) / FREQUENCIES[i]
                        )
                    ),
                )

                level = int(self.cfg["gains"][nearest] * 100)
                level = max(
                    int(band_range[0]),
                    min(int(band_range[1]), level),
                )
                self.eq.setBandLevel(band, level)

            if bass_enabled:
                self.bass.setStrength(int(self.cfg["bass"] * 10))

            if stereo_enabled:
                self.virtualizer.setStrength(int(self.cfg["stereo"] * 10))

        except Exception as exc:
            print("Could not apply audio effects:", exc)


engine = AudioEngine()


def main(page: ft.Page):
    page.title = "Aqualizer"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#0B0E14"
    page.padding = 10

    if not IS_ANDROID:
        page.window.maximized = False
        page.window.full_screen = False
        page.window.width = 420
        page.window.height = 800
        page.window.resizable = False

    cfg = engine.cfg
    band_sliders = []
    band_values = []
    fx_sliders = {}
    fx_values = {}

    power_switch = ft.Switch(
        value=cfg["enabled"],
        active_color="#00E5A0",
        inactive_thumb_color="#5A6172",
        inactive_track_color="#1C2230",
    )

    bars = [
        ft.Container(
            width=22,
            height=10,
            bgcolor="#00E5A0",
            border_radius=4,
            animate=ft.Animation(120, ft.AnimationCurve.EASE_OUT),
        )
        for _ in range(10)
    ]

    spectrum = ft.Container(
        height=100,
        border_radius=14,
        bgcolor="#11151F",
        padding=10,
        content=ft.Row(
            controls=bars,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.END,
        ),
    )

    def dropdown_options():
        names = (
            list(BUILTIN_PRESETS)
            + list(cfg["custom_presets"])
            + ["Custom"]
        )
        return [ft.DropdownOption(key=n, text=n) for n in names]

    preset_dd = ft.Dropdown(
        value=cfg["preset"],
        options=dropdown_options(),
        width=145,
        height=40,
        text_size=12,
        bgcolor="#11151F",
        color="#E6EAF2",
        border_color="#1C2230",
        focused_border_color="#00E5A0",
    )

    def mark_custom():
        cfg["preset"] = "Custom"
        preset_dd.value = "Custom"

    def make_band(index):
        value_text = ft.Text(
            f"{cfg['gains'][index]:+.1f}",
            size=9,
            color="#8B93A7",
        )
        band_values.append(value_text)

        slider = ft.Slider(
            min=-12,
            max=12,
            divisions=48,
            value=cfg["gains"][index],
            active_color="#00E5A0",
            inactive_color="#1C2230",
            thumb_color="#FFFFFF",
            width=150,
            height=30,
        )

        def changed(event):
            value = round(float(event.control.value), 1)
            cfg["gains"][index] = value
            value_text.value = f"{value:+.1f}"
            mark_custom()
            page.update()

        slider.on_change = changed
        slider.on_change_end = lambda e: engine.apply()
        band_sliders.append(slider)

        return ft.Column(
            controls=[
                ft.Container(
                    width=32,
                    height=160,
                    alignment=ft.Alignment.CENTER,
                    content=ft.RotatedBox(
                        quarter_turns=3,
                        content=slider,
                    ),
                ),
                ft.Text(BAND_LABELS[index], size=9, color="#8B93A7"),
                value_text,
            ],
            spacing=2,
            width=32,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

    bands_row = ft.Row(
        controls=[make_band(i) for i in range(10)],
        spacing=0,
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        scroll=ft.ScrollMode.AUTO,
    )

    def make_fx_row(label, key, color, icon):
        value_text = ft.Text(
            str(round(cfg[key])),
            size=11,
            color="#8B93A7",
            width=28,
        )
        fx_values[key] = value_text

        slider = ft.Slider(
            min=0,
            max=100,
            divisions=100,
            value=cfg[key],
            active_color=color,
            inactive_color="#1C2230",
            thumb_color="#FFFFFF",
        )
        fx_sliders[key] = slider

        def changed(event):
            cfg[key] = round(float(event.control.value))
            value_text.value = str(cfg[key])
            mark_custom()
            page.update()

        slider.on_change = changed
        slider.on_change_end = lambda e: engine.apply()

        return ft.Row(
            controls=[
                ft.Icon(icon, size=16, color=color),
                ft.Text(label, size=11, color="#B7BFD0", width=75),
                ft.Container(content=slider, expand=True),
                value_text,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    bass_row = make_fx_row(
        "Bass Boost", "bass", "#FF6B6B", ft.Icons.SPEAKER
    )
    stereo_row = make_fx_row(
        "Stereo / 3D",
        "stereo",
        "#7C5CFF",
        ft.Icons.SURROUND_SOUND,
    )

    def select_preset(event):
        name = event.control.value

        if name in BUILTIN_PRESETS:
            snapshot = {
                "gains": BUILTIN_PRESETS[name],
                "bass": 0,
                "stereo": 0,
            }
        elif name in cfg["custom_presets"]:
            snapshot = cfg["custom_presets"][name]
        else:
            return

        cfg["gains"] = [float(v) for v in snapshot["gains"]]
        cfg["bass"] = float(snapshot["bass"])
        cfg["stereo"] = float(snapshot["stereo"])
        cfg["preset"] = name

        for index, value in enumerate(cfg["gains"]):
            band_sliders[index].value = value
            band_values[index].value = f"{value:+.1f}"

        for key in ("bass", "stereo"):
            fx_sliders[key].value = cfg[key]
            fx_values[key].value = str(round(cfg[key]))

        engine.apply()
        page.update()

    preset_dd.on_select = select_preset

    name_input = ft.TextField(
        label="نام پریست",
        autofocus=True,
        border_color="#00E5A0",
    )
    name_error = ft.Text("", size=11, color="#FF6B6B")

    def save_named_preset(event):
        name = (name_input.value or "").strip()

        if not name:
            name_error.value = "نام پریست را وارد کنید."
            page.update()
            return

        if name in BUILTIN_PRESETS or name in cfg["custom_presets"] or name == "Custom":
            name_error.value = "این نام قبلاً استفاده شده است."
            page.update()
            return

        cfg["custom_presets"][name] = {
            "gains": list(cfg["gains"]),
            "bass": cfg["bass"],
            "stereo": cfg["stereo"],
        }
        cfg["preset"] = name
        preset_dd.options = dropdown_options()
        preset_dd.value = name

        engine.apply()
        page.pop_dialog()
        page.update()

    save_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("ذخیرهٔ پریست"),
        content=ft.Column(
            controls=[name_input, name_error],
            spacing=5,
            tight=True,
        ),
        actions=[
            ft.TextButton(
                "لغو",
                on_click=lambda e: page.pop_dialog(),
            ),
            ft.TextButton(
                "ذخیره",
                on_click=save_named_preset,
            ),
        ],
        bgcolor="#161B26",
    )

    def open_save_dialog(event):
        name_input.value = ""
        name_error.value = ""
        page.show_dialog(save_dialog)

    save_button = ft.IconButton(
        icon=ft.Icons.SAVE,
        icon_color="#00E5A0",
        tooltip="ذخیرهٔ پریست با نام دلخواه",
        on_click=open_save_dialog,
    )

    def toggle_power(event):
        cfg["enabled"] = bool(event.control.value)
        engine.apply()
        page.update()

    power_switch.on_change = toggle_power

    async def animate_spectrum():
        # این نمودار صرفاً انیمیشن رابط کاربری است؛ FFT صدای واقعی نیست.
        while True:
            for index, bar in enumerate(bars):
                base = 10 + (cfg["gains"][index] + 12) * 2.8
                jitter = random.uniform(0.7, 1.3)
                bar.height = (
                    max(6, min(85, base * jitter))
                    if cfg["enabled"] else 6
                )
                bar.bgcolor = (
                    "#00E5A0" if cfg["enabled"] else "#2A3142"
                )

            try:
                page.update()
            except Exception:
                break

            await asyncio.sleep(0.12)

    header = ft.Container(
        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        content=ft.Row(
            controls=[
                ft.Text(
                    "AQUALIZER",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color="#E6EAF2",
                ),
                ft.Container(expand=True),
                power_switch,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    eq_card = ft.Container(
        margin=ft.Margin.symmetric(horizontal=4),
        padding=10,
        border_radius=16,
        bgcolor="#11151F",
        border=ft.Border.all(1, "#1C2230"),
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text(
                            "Equalizer",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color="#E6EAF2",
                        ),
                        ft.Container(expand=True),
                        preset_dd,
                        save_button,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=4),
                bands_row,
            ],
            spacing=6,
        ),
    )

    fx_card = ft.Container(
        margin=ft.Margin.symmetric(horizontal=4, vertical=6),
        padding=10,
        border_radius=16,
        bgcolor="#11151F",
        border=ft.Border.all(1, "#1C2230"),
        content=ft.Column(
            controls=[
                ft.Text(
                    "Audio Effects",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color="#E6EAF2",
                ),
                bass_row,
                stereo_row,
            ],
            spacing=6,
        ),
    )

    page.add(
        ft.Column(
            controls=[
                header,
                ft.Container(
                    content=spectrum,
                    margin=ft.Margin.symmetric(horizontal=4),
                ),
                eq_card,
                fx_card,
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
    )

    page.run_task(animate_spectrum)


if __name__ == "__main__":
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        ft.run(main)
    else:
        # برای اجرای %runfile در Spyder
        import nest_asyncio
        nest_asyncio.apply()
        ft.run(main)
