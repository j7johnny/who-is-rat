from __future__ import annotations

from collections import OrderedDict

from django import forms

from library.models import AntiOcrPreset, Chapter, CustomFontUpload, Novel
from library.services.anti7ocr_config import (
    PRESET_NAME_CHOICES,
    build_snapshot,
    default_preset_snapshot,
    normalize_preset_snapshot,
)
from library.services.anti7ocr_diagnostics import DEFAULT_PREVIEW_TEXT


def _number_widget(*, step: str = "1", minimum: str | None = None, maximum: str | None = None) -> forms.NumberInput:
    attrs = {"step": step}
    if minimum is not None:
        attrs["min"] = minimum
    if maximum is not None:
        attrs["max"] = maximum
    return forms.NumberInput(attrs=attrs)


def _parse_color_triplet(value: str, label: str) -> list[int]:
    parts = [item.strip() for item in value.split(",")]
    if len(parts) != 3:
        raise forms.ValidationError(f"{label} 請使用 `R,G,B` 格式。")
    try:
        colors = [int(item) for item in parts]
    except ValueError as exc:
        raise forms.ValidationError(f"{label} 只能填入數字。") from exc
    for color in colors:
        if color < 0 or color > 255:
            raise forms.ValidationError(f"{label} 每個數值都必須介於 0 到 255。")
    return colors


class WatermarkExtractForm(forms.Form):
    image = forms.ImageField(
        label="上傳圖片",
        help_text="可上傳站內原圖、單張截圖或多張連續頁面的長截圖。系統會先做全圖提取，再自動改用區塊裁切搜尋。",
    )


class NovelAdminForm(forms.ModelForm):
    class Meta:
        model = Novel
        fields = "__all__"
        help_texts = {
            "slug": "小說代稱主要用在後台辨識與資料一致性，前台閱讀網址目前不使用它。",
        }


class ChapterAdminForm(forms.ModelForm):
    class Meta:
        model = Chapter
        fields = "__all__"
        help_texts = {
            "slug": "章節代稱主要用在後台與資料唯一性，不直接顯示在讀者閱讀網址。",
            "sort_order": "章節在同一本小說中的排序。",
            "anti_ocr_preset": "若未指定，發布時會自動使用全站預設的 anti7ocr 設定。",
        }


class AntiOcrPresetConfigForm(forms.ModelForm):
    base_preset_name = forms.ChoiceField(
        label="基底 preset",
        choices=PRESET_NAME_CHOICES,
        help_text="先選 anti7ocr 內建基底，再覆蓋下面的細部參數。",
    )
    preview_text = forms.CharField(
        label="示範文字",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="按下「產生示範圖片」時會使用這段文字。留空時會使用系統預設示範段落。",
    )
    preview_device_profile = forms.ChoiceField(
        label="示範裝置",
        choices=[("desktop", "桌機"), ("mobile", "手機")],
        initial="desktop",
    )
    preview_font_id = forms.ChoiceField(
        label="示範字體",
        required=False,
        help_text="可指定一個已上傳且啟用的字體來產生示範圖；留空時會依目前啟用字體自動選擇。",
    )

    unicode_normalization = forms.ChoiceField(
        label="Unicode 正規化",
        choices=[("NFC", "NFC"), ("NFKC", "NFKC"), ("NFD", "NFD"), ("NFKD", "NFKD")],
    )
    enable_char_to_pinyin = forms.BooleanField(
        label="啟用局部拼音",
        required=False,
        help_text="預設建議關閉。啟用後可提高干擾，但通常也會降低閱讀舒適度。",
    )
    char_to_pinyin_ratio = forms.FloatField(
        label="拼音比例",
        widget=_number_widget(step="0.01", minimum="0", maximum="1"),
    )
    enable_char_reverse = forms.BooleanField(
        label="啟用倒字/翻轉",
        required=False,
        help_text="預設建議關閉。這類效果對閱讀體驗影響最大。",
    )
    char_reverse_ratio = forms.FloatField(
        label="倒字比例",
        widget=_number_widget(step="0.01", minimum="0", maximum="1"),
    )
    reverse_rotation_min = forms.IntegerField(label="翻轉角度最小值", widget=_number_widget(minimum="0", maximum="360"))
    reverse_rotation_max = forms.IntegerField(label="翻轉角度最大值", widget=_number_widget(minimum="0", maximum="360"))

    canvas_background_color = forms.CharField(
        label="背景底色",
        help_text="請輸入 `R,G,B`，例如 `255,255,255`。",
    )
    canvas_text_color = forms.CharField(
        label="文字主色",
        help_text="請輸入 `R,G,B`，例如 `20,20,20`。",
    )
    canvas_dpi = forms.IntegerField(label="輸出 DPI", widget=_number_widget(minimum="72", maximum="600"))
    background_enable = forms.BooleanField(label="啟用背景字干擾", required=False)
    background_min_font_size = forms.IntegerField(label="背景字最小字級", widget=_number_widget(minimum="6", maximum="128"))
    background_max_font_size = forms.IntegerField(label="背景字最大字級", widget=_number_widget(minimum="6", maximum="256"))
    background_foreground_color = forms.CharField(
        label="背景字顏色",
        help_text="請輸入 `R,G,B`，例如 `130,130,130`。",
    )

    fragment_enable = forms.BooleanField(label="啟用筆畫碎裂", required=False)
    stroke_fragmentation_prob = forms.FloatField(
        label="筆畫碎裂機率",
        widget=_number_widget(step="0.01", minimum="0", maximum="1"),
        help_text="數值越高，筆畫越容易出現缺角或斷裂。",
    )
    closed_structure_break_prob = forms.FloatField(
        label="封閉字形破口機率",
        widget=_number_widget(step="0.01", minimum="0", maximum="1"),
        help_text="例如「回、國、圓」這類封閉結構被打開的機率。",
    )
    closed_structure_chars = forms.CharField(
        label="封閉字形字集",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="要優先施加破口效果的字集。",
    )
    erase_width = forms.IntegerField(label="碎裂寬度", widget=_number_widget(minimum="0", maximum="16"))
    erase_ratio = forms.FloatField(label="碎裂比例", widget=_number_widget(step="0.01", minimum="0", maximum="1"))
    max_stroke_fragments = forms.IntegerField(label="單字最大筆畫碎裂次數", widget=_number_widget(minimum="0", maximum="8"))
    max_closed_breaks = forms.IntegerField(label="單字最大封閉破口次數", widget=_number_widget(minimum="0", maximum="8"))

    perturb_enable = forms.BooleanField(label="啟用細部擾動", required=False)
    edge_jitter_strength = forms.FloatField(label="邊緣抖動強度", widget=_number_widget(step="0.01", minimum="0", maximum="1"))
    edge_brightness_noise = forms.IntegerField(label="邊緣亮度噪聲", widget=_number_widget(minimum="0", maximum="255"))
    local_contrast_noise = forms.FloatField(label="局部對比干擾", widget=_number_widget(step="0.01", minimum="0", maximum="1"))
    local_contrast_patches = forms.IntegerField(label="局部對比區塊數", widget=_number_widget(minimum="0", maximum="1000"))
    adversarial_watermark_enable = forms.BooleanField(label="啟用細字浮層", required=False)
    watermark_text = forms.CharField(label="細字浮層內容", max_length=100)
    watermark_opacity = forms.IntegerField(label="細字透明度", widget=_number_widget(minimum="0", maximum="255"))
    watermark_density = forms.FloatField(label="細字密度", widget=_number_widget(step="0.01", minimum="0", maximum="1"))
    watermark_scale = forms.FloatField(label="細字大小倍率", widget=_number_widget(step="0.01", minimum="0", maximum="5"))

    export_format = forms.ChoiceField(
        label="輸出格式",
        choices=[("PNG", "PNG"), ("JPEG", "JPEG"), ("WEBP", "WEBP")],
        help_text="閱讀站建議維持 PNG，最有利於 blind watermark 與提取穩定度。",
    )
    export_quality = forms.IntegerField(label="輸出品質", widget=_number_widget(minimum="1", maximum="100"))

    desktop_canvas_width = forms.IntegerField(label="桌機寬度", widget=_number_widget(minimum="120", maximum="600"))
    desktop_canvas_height = forms.IntegerField(label="桌機基準高度", widget=_number_widget(minimum="120", maximum="200000"))
    desktop_canvas_margin = forms.IntegerField(label="桌機邊距", widget=_number_widget(minimum="0", maximum="200"))
    desktop_canvas_supersample = forms.IntegerField(label="桌機 supersample", widget=_number_widget(minimum="1", maximum="4"))
    desktop_max_chars_per_line = forms.IntegerField(label="桌機每行字數上限", widget=_number_widget(minimum="1", maximum="200"))
    desktop_line_height_multiplier = forms.FloatField(label="桌機行高倍率", widget=_number_widget(step="0.01", minimum="0.5", maximum="5"))
    desktop_micro_kerning_jitter = forms.FloatField(label="桌機字距抖動", widget=_number_widget(step="0.01", minimum="0", maximum="10"))
    desktop_baseline_jitter = forms.FloatField(label="桌機基線抖動", widget=_number_widget(step="0.01", minimum="0", maximum="10"))
    desktop_character_scale_jitter = forms.FloatField(label="桌機字級抖動", widget=_number_widget(step="0.01", minimum="0", maximum="1"))
    desktop_min_size = forms.IntegerField(label="桌機最小字級", widget=_number_widget(minimum="8", maximum="256"))
    desktop_max_size = forms.IntegerField(label="桌機最大字級", widget=_number_widget(minimum="8", maximum="256"))
    desktop_background_density = forms.FloatField(label="桌機背景字密度", widget=_number_widget(step="0.01", minimum="0", maximum="1"))

    mobile_canvas_width = forms.IntegerField(label="手機寬度", widget=_number_widget(minimum="120", maximum="600"))
    mobile_canvas_height = forms.IntegerField(label="手機基準高度", widget=_number_widget(minimum="120", maximum="200000"))
    mobile_canvas_margin = forms.IntegerField(label="手機邊距", widget=_number_widget(minimum="0", maximum="200"))
    mobile_canvas_supersample = forms.IntegerField(label="手機 supersample", widget=_number_widget(minimum="1", maximum="4"))
    mobile_max_chars_per_line = forms.IntegerField(label="手機每行字數上限", widget=_number_widget(minimum="1", maximum="200"))
    mobile_line_height_multiplier = forms.FloatField(label="手機行高倍率", widget=_number_widget(step="0.01", minimum="0.5", maximum="5"))
    mobile_micro_kerning_jitter = forms.FloatField(label="手機字距抖動", widget=_number_widget(step="0.01", minimum="0", maximum="10"))
    mobile_baseline_jitter = forms.FloatField(label="手機基線抖動", widget=_number_widget(step="0.01", minimum="0", maximum="10"))
    mobile_character_scale_jitter = forms.FloatField(label="手機字級抖動", widget=_number_widget(step="0.01", minimum="0", maximum="1"))
    mobile_min_size = forms.IntegerField(label="手機最小字級", widget=_number_widget(minimum="8", maximum="256"))
    mobile_max_size = forms.IntegerField(label="手機最大字級", widget=_number_widget(minimum="8", maximum="256"))
    mobile_background_density = forms.FloatField(label="手機背景字密度", widget=_number_widget(step="0.01", minimum="0", maximum="1"))

    group_definitions = [
        {
            "title": "基本資料",
            "description": "先決定這份設定的名稱、是否為預設，以及示範圖片要用哪段文字與哪種裝置尺寸。",
            "fields": ("name", "is_default", "base_preset_name", "preview_text", "preview_device_profile", "preview_font_id"),
        },
        {
            "title": "文字保護",
            "description": "控制拼音、倒字與字元處理方式。若以閱讀優先為主，建議維持關閉。",
            "fields": ("unicode_normalization", "enable_char_to_pinyin", "char_to_pinyin_ratio", "enable_char_reverse", "char_reverse_ratio", "reverse_rotation_min", "reverse_rotation_max"),
        },
        {
            "title": "桌機版面",
            "description": "決定桌機閱讀時的寬度、每行字數、字級與抖動強度。",
            "fields": ("desktop_canvas_width", "desktop_canvas_height", "desktop_canvas_margin", "desktop_canvas_supersample", "desktop_max_chars_per_line", "desktop_line_height_multiplier", "desktop_micro_kerning_jitter", "desktop_baseline_jitter", "desktop_character_scale_jitter", "desktop_min_size", "desktop_max_size", "desktop_background_density"),
        },
        {
            "title": "手機版面",
            "description": "決定手機閱讀時的寬度、每行字數、字級與抖動強度。",
            "fields": ("mobile_canvas_width", "mobile_canvas_height", "mobile_canvas_margin", "mobile_canvas_supersample", "mobile_max_chars_per_line", "mobile_line_height_multiplier", "mobile_micro_kerning_jitter", "mobile_baseline_jitter", "mobile_character_scale_jitter", "mobile_min_size", "mobile_max_size", "mobile_background_density"),
        },
        {
            "title": "背景與色彩",
            "description": "控制主文字顏色、背景底色，以及背景字干擾的字級與色彩。",
            "fields": ("canvas_background_color", "canvas_text_color", "canvas_dpi", "background_enable", "background_min_font_size", "background_max_font_size", "background_foreground_color"),
        },
        {
            "title": "碎裂效果",
            "description": "控制缺角、破口與封閉字形破壞程度。強度越高，OCR 越難，但可讀性也會下降。",
            "fields": ("fragment_enable", "stroke_fragmentation_prob", "closed_structure_break_prob", "closed_structure_chars", "erase_width", "erase_ratio", "max_stroke_fragments", "max_closed_breaks"),
        },
        {
            "title": "細部擾動",
            "description": "控制邊緣抖動、局部對比與細字浮層。這些通常比倒字更容易兼顧閱讀體驗。",
            "fields": ("perturb_enable", "edge_jitter_strength", "edge_brightness_noise", "local_contrast_noise", "local_contrast_patches", "adversarial_watermark_enable", "watermark_text", "watermark_opacity", "watermark_density", "watermark_scale"),
        },
        {
            "title": "輸出",
            "description": "正式閱讀站建議維持 PNG，避免壓縮影響 blind watermark 的穩定度。",
            "fields": ("export_format", "export_quality"),
        },
    ]

    class Meta:
        model = AntiOcrPreset
        fields = ("name", "is_default", "base_preset_name")
        help_texts = {
            "name": "請填一個管理者看得懂的名稱，例如「網站預設（閱讀優先）」。",
            "is_default": "未指定 preset 的章節，發布時會自動使用這份設定。",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_fonts = list(CustomFontUpload.objects.filter(is_active=True).order_by("name"))
        self.fields["preview_font_id"].choices = [("", "自動選擇（啟用字體優先）")] + [
            (str(font.id), font.name) for font in active_fonts
        ]
        snapshot = self._snapshot_for_initial()
        self._apply_initial_from_snapshot(snapshot)
        self.fields["preview_text"].initial = DEFAULT_PREVIEW_TEXT
        if active_fonts and not self.is_bound:
            self.fields["preview_font_id"].initial = str(active_fonts[0].id)
        if self.is_bound and self.data.get("action") == "preview":
            bound_data = self.data.copy()
            for field_name, field in self.fields.items():
                if field_name in {"preview_text", "preview_device_profile", "preview_font_id"}:
                    continue
                if isinstance(field.widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                    continue
                current_value = bound_data.get(field_name)
                if current_value not in ("", None):
                    continue
                initial_value = self.initial.get(field_name, field.initial)
                if initial_value in ("", None):
                    continue
                bound_data[field_name] = str(initial_value)
            self.data = bound_data
        self.grouped_fields = [
            {
                "title": group["title"],
                "description": group["description"],
                "fields": [self[field_name] for field_name in group["fields"]],
            }
            for group in self.group_definitions
        ]

    def _snapshot_for_initial(self) -> dict:
        if self.instance.pk:
            return normalize_preset_snapshot(self.instance.as_snapshot())
        return default_preset_snapshot()

    def _apply_initial_from_snapshot(self, snapshot: dict) -> None:
        shared = snapshot["shared_config"]
        desktop = snapshot["desktop_config"]
        mobile = snapshot["mobile_config"]
        text_cfg = shared["text"]
        canvas_cfg = shared["canvas"]
        background_cfg = shared["background"]
        fragment_cfg = shared["fragment"]
        perturb_cfg = shared["perturb"]
        export_cfg = shared["export"]
        self.initial.update(
            {
                "base_preset_name": snapshot["base_preset_name"],
                "unicode_normalization": text_cfg["unicode_normalization"],
                "enable_char_to_pinyin": text_cfg["enable_char_to_pinyin"],
                "char_to_pinyin_ratio": text_cfg["char_to_pinyin_ratio"],
                "enable_char_reverse": text_cfg["enable_char_reverse"],
                "char_reverse_ratio": text_cfg["char_reverse_ratio"],
                "reverse_rotation_min": text_cfg["reverse_rotation_range"][0],
                "reverse_rotation_max": text_cfg["reverse_rotation_range"][1],
                "canvas_background_color": ",".join(str(item) for item in canvas_cfg["background_color"]),
                "canvas_text_color": ",".join(str(item) for item in canvas_cfg["text_color"]),
                "canvas_dpi": canvas_cfg["dpi"],
                "background_enable": background_cfg["enable"],
                "background_min_font_size": background_cfg["min_font_size"],
                "background_max_font_size": background_cfg["max_font_size"],
                "background_foreground_color": ",".join(str(item) for item in background_cfg["foreground"]),
                "fragment_enable": fragment_cfg["enable"],
                "stroke_fragmentation_prob": fragment_cfg["stroke_fragmentation_prob"],
                "closed_structure_break_prob": fragment_cfg["closed_structure_break_prob"],
                "closed_structure_chars": fragment_cfg["closed_structure_chars"],
                "erase_width": fragment_cfg["erase_width"],
                "erase_ratio": fragment_cfg["erase_ratio"],
                "max_stroke_fragments": fragment_cfg["max_stroke_fragments"],
                "max_closed_breaks": fragment_cfg["max_closed_breaks"],
                "perturb_enable": perturb_cfg["enable"],
                "edge_jitter_strength": perturb_cfg["edge_jitter_strength"],
                "edge_brightness_noise": perturb_cfg["edge_brightness_noise"],
                "local_contrast_noise": perturb_cfg["local_contrast_noise"],
                "local_contrast_patches": perturb_cfg["local_contrast_patches"],
                "adversarial_watermark_enable": perturb_cfg["adversarial_watermark_enable"],
                "watermark_text": perturb_cfg["watermark_text"],
                "watermark_opacity": perturb_cfg["watermark_opacity"],
                "watermark_density": perturb_cfg["watermark_density"],
                "watermark_scale": perturb_cfg["watermark_scale"],
                "export_format": export_cfg["format"],
                "export_quality": export_cfg["quality"],
            }
        )
        self.initial.update(self._device_initial("desktop", desktop))
        self.initial.update(self._device_initial("mobile", mobile))

    def _device_initial(self, prefix: str, config: dict) -> dict:
        return {
            f"{prefix}_canvas_width": config["canvas"]["width"],
            f"{prefix}_canvas_height": config["canvas"]["height"],
            f"{prefix}_canvas_margin": config["canvas"]["margin"],
            f"{prefix}_canvas_supersample": config["canvas"]["supersample"],
            f"{prefix}_max_chars_per_line": config["layout"]["max_chars_per_line"],
            f"{prefix}_line_height_multiplier": config["layout"]["line_height_multiplier"],
            f"{prefix}_micro_kerning_jitter": config["layout"]["micro_kerning_jitter"],
            f"{prefix}_baseline_jitter": config["layout"]["baseline_jitter"],
            f"{prefix}_character_scale_jitter": config["layout"]["character_scale_jitter"],
            f"{prefix}_min_size": config["font"]["min_size"],
            f"{prefix}_max_size": config["font"]["max_size"],
            f"{prefix}_background_density": config["background"]["density"],
        }

    def clean(self):
        cleaned_data = super().clean()
        if self.errors:
            return cleaned_data

        shared_config = {
            "text": {
                "unicode_normalization": cleaned_data["unicode_normalization"],
                "enable_char_to_pinyin": cleaned_data["enable_char_to_pinyin"],
                "char_to_pinyin_ratio": cleaned_data["char_to_pinyin_ratio"],
                "enable_char_reverse": cleaned_data["enable_char_reverse"],
                "char_reverse_ratio": cleaned_data["char_reverse_ratio"],
                "reverse_rotation_range": [cleaned_data["reverse_rotation_min"], cleaned_data["reverse_rotation_max"]],
            },
            "canvas": {
                "background_color": _parse_color_triplet(cleaned_data["canvas_background_color"], "背景底色"),
                "text_color": _parse_color_triplet(cleaned_data["canvas_text_color"], "文字主色"),
                "dpi": cleaned_data["canvas_dpi"],
            },
            "background": {
                "enable": cleaned_data["background_enable"],
                "min_font_size": cleaned_data["background_min_font_size"],
                "max_font_size": cleaned_data["background_max_font_size"],
                "foreground": _parse_color_triplet(cleaned_data["background_foreground_color"], "背景字顏色"),
            },
            "fragment": {
                "enable": cleaned_data["fragment_enable"],
                "stroke_fragmentation_prob": cleaned_data["stroke_fragmentation_prob"],
                "closed_structure_break_prob": cleaned_data["closed_structure_break_prob"],
                "closed_structure_chars": cleaned_data["closed_structure_chars"],
                "erase_width": cleaned_data["erase_width"],
                "erase_ratio": cleaned_data["erase_ratio"],
                "max_stroke_fragments": cleaned_data["max_stroke_fragments"],
                "max_closed_breaks": cleaned_data["max_closed_breaks"],
            },
            "perturb": {
                "enable": cleaned_data["perturb_enable"],
                "edge_jitter_strength": cleaned_data["edge_jitter_strength"],
                "edge_brightness_noise": cleaned_data["edge_brightness_noise"],
                "local_contrast_noise": cleaned_data["local_contrast_noise"],
                "local_contrast_patches": cleaned_data["local_contrast_patches"],
                "adversarial_watermark_enable": cleaned_data["adversarial_watermark_enable"],
                "watermark_text": cleaned_data["watermark_text"],
                "watermark_opacity": cleaned_data["watermark_opacity"],
                "watermark_density": cleaned_data["watermark_density"],
                "watermark_scale": cleaned_data["watermark_scale"],
            },
            "export": {
                "format": cleaned_data["export_format"],
                "quality": cleaned_data["export_quality"],
            },
        }
        desktop_config = self._device_cleaned("desktop", cleaned_data)
        mobile_config = self._device_cleaned("mobile", cleaned_data)

        try:
            snapshot = build_snapshot(
                base_preset_name=cleaned_data["base_preset_name"],
                shared_config=shared_config,
                desktop_config=desktop_config,
                mobile_config=mobile_config,
            )
        except forms.ValidationError as exc:
            self.add_error(None, exc.message)
            return cleaned_data
        self._snapshot = snapshot
        return cleaned_data

    def _device_cleaned(self, prefix: str, cleaned_data: dict) -> dict:
        return {
            "canvas": {
                "width": cleaned_data[f"{prefix}_canvas_width"],
                "height": cleaned_data[f"{prefix}_canvas_height"],
                "margin": cleaned_data[f"{prefix}_canvas_margin"],
                "supersample": cleaned_data[f"{prefix}_canvas_supersample"],
            },
            "layout": {
                "max_chars_per_line": cleaned_data[f"{prefix}_max_chars_per_line"],
                "line_height_multiplier": cleaned_data[f"{prefix}_line_height_multiplier"],
                "micro_kerning_jitter": cleaned_data[f"{prefix}_micro_kerning_jitter"],
                "baseline_jitter": cleaned_data[f"{prefix}_baseline_jitter"],
                "character_scale_jitter": cleaned_data[f"{prefix}_character_scale_jitter"],
            },
            "font": {
                "min_size": cleaned_data[f"{prefix}_min_size"],
                "max_size": cleaned_data[f"{prefix}_max_size"],
            },
            "background": {
                "density": cleaned_data[f"{prefix}_background_density"],
            },
        }

    @property
    def prepared_snapshot(self) -> dict:
        snapshot = getattr(self, "_snapshot", None)
        if snapshot is None:
            raise RuntimeError("Preset snapshot is not ready. Call is_valid() first.")
        return snapshot

    def save(self, commit: bool = True) -> AntiOcrPreset:
        preset = super().save(commit=False)
        snapshot = self.prepared_snapshot
        preset.base_preset_name = snapshot["base_preset_name"]
        preset.shared_config = snapshot["shared_config"]
        preset.desktop_config = snapshot["desktop_config"]
        preset.mobile_config = snapshot["mobile_config"]
        if commit:
            preset.save()
            if preset.is_default:
                AntiOcrPreset.objects.exclude(pk=preset.pk).filter(is_default=True).update(is_default=False)
        return preset


class AntiOcrPresetAdminForm(AntiOcrPresetConfigForm):
    pass
