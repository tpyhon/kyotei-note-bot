# src/data/models.py
"""
競艇データのデータクラス定義

BoatraceOpenAPI から取得した実際のJSONキーに基づいて定義。
全クラスは dataclass で定義し、APIレスポンスのdictから生成する from_dict() を持つ。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ──────────────────────────────────────────
# None セーフな変換ヘルパー
# ──────────────────────────────────────────

def _int(v, default: int = 0) -> int:
    """None・空文字を default に変換してから int に変換する。"""
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _float(v, default: float = 0.0) -> float:
    """None・空文字を default に変換してから float に変換する。"""
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _str(v, default: str = "") -> str:
    """None を default に変換してから str に変換する。"""
    if v is None:
        return default
    return str(v)


# ──────────────────────────────────────────
# コード → 名称 変換テーブル
# ──────────────────────────────────────────

CLASS_MAP: dict[int, str] = {
    1: "A1", 2: "A2", 3: "B1", 4: "B2",
}

BRANCH_MAP: dict[int, str] = {
    1:  "群馬",   2:  "埼玉",   3:  "東京",   4:  "神奈川",
    5:  "愛知",   6:  "静岡",   7:  "三重",   8:  "滋賀",
    9:  "大阪",   10: "兵庫",   11: "福岡",   12: "佐賀",
    13: "長崎",   14: "熊本",   15: "大分",   16: "宮崎",
    17: "鹿児島", 18: "福井",   19: "山口",   20: "徳島",
    21: "香川",   22: "愛媛",   23: "高知",   24: "広島",
    25: "岡山",   26: "島根",   27: "鳥取",   28: "奈良",
}

STADIUM_MAP: dict[int, tuple[str, str]] = {
    1:  ("桐生",   "01"),  2:  ("戸田",   "02"),
    3:  ("江戸川", "03"),  4:  ("平和島", "04"),
    5:  ("多摩川", "05"),  6:  ("浜名湖", "06"),
    7:  ("蒲郡",   "07"),  8:  ("常滑",   "08"),
    9:  ("津",     "09"),  10: ("三国",   "10"),
    11: ("びわこ", "11"),  12: ("住之江", "12"),
    13: ("尼崎",   "13"),  14: ("鳴門",   "14"),
    15: ("丸亀",   "15"),  16: ("児島",   "16"),
    17: ("宮島",   "17"),  18: ("徳山",   "18"),
    19: ("下関",   "19"),  20: ("若松",   "20"),
    21: ("芦屋",   "21"),  22: ("福岡",   "22"),
    23: ("唐津",   "23"),  24: ("大村",   "24"),
}

WEATHER_MAP: dict[int, str] = {
    1: "晴", 2: "曇", 3: "雨", 4: "雪",
}

WIND_DIR_MAP: dict[int, str] = {
    1: "北",  2: "北東", 3: "東",  4: "南東",
    5: "南",  6: "南西", 7: "西",  8: "北西",
}

TECHNIQUE_MAP: dict[int, str] = {
    1: "逃げ", 2: "差し", 3: "まくり",
    4: "まくり差し", 5: "抜き", 6: "恵まれ",
}


# ──────────────────────────────────────────
# 選手・モーター・ボート
# ──────────────────────────────────────────

@dataclass
class RacerProfile:
    """
    出走選手のプロフィール・成績情報。
    出走表 (programs) の boats[] から取得。
    """
    racer_number: int
    name: str
    branch: str
    age: int
    weight: float
    grade: str
    flying_count: int
    late_count: int
    avg_start_timing: float
    national_win_rate: float
    national_in2_rate: float
    national_in3_rate: float
    local_win_rate: float
    local_in2_rate: float
    local_in3_rate: float

    @classmethod
    def from_dict(cls, d: dict) -> RacerProfile:
        class_num  = _int(d.get("racer_class_number"), 3)
        branch_num = _int(d.get("racer_branch_number"), 0)
        return cls(
            racer_number      = _int(d.get("racer_number")),
            name              = _str(d.get("racer_name")),
            branch            = BRANCH_MAP.get(branch_num, f"支部{branch_num}"),
            age               = _int(d.get("racer_age")),
            weight            = _float(d.get("racer_weight")),
            grade             = CLASS_MAP.get(class_num, "B1"),
            flying_count      = _int(d.get("racer_flying_count")),
            late_count        = _int(d.get("racer_late_count")),
            avg_start_timing  = _float(d.get("racer_average_start_timing")),
            national_win_rate = _float(d.get("racer_national_top_1_percent")),
            national_in2_rate = _float(d.get("racer_national_top_2_percent")),
            national_in3_rate = _float(d.get("racer_national_top_3_percent")),
            local_win_rate    = _float(d.get("racer_local_top_1_percent")),
            local_in2_rate    = _float(d.get("racer_local_top_2_percent")),
            local_in3_rate    = _float(d.get("racer_local_top_3_percent")),
        )

    @property
    def is_a_class(self) -> bool:
        return self.grade.startswith("A")

    @property
    def grade_score(self) -> int:
        """級別を数値スコアに変換（予測モデル用）。A1=4, A2=3, B1=2, B2=1"""
        return {"A1": 4, "A2": 3, "B1": 2, "B2": 1}.get(self.grade, 1)


@dataclass
class MotorBoat:
    """
    モーター・ボートの成績情報。
    出走表 (programs) の boats[] から取得。
    """
    motor_number: int
    motor_in2_rate: float
    motor_in3_rate: float
    boat_number: int
    boat_in2_rate: float
    boat_in3_rate: float

    @classmethod
    def from_dict(cls, d: dict) -> MotorBoat:
        return cls(
            motor_number   = _int(d.get("racer_assigned_motor_number")),
            motor_in2_rate = _float(d.get("racer_assigned_motor_top_2_percent")),
            motor_in3_rate = _float(d.get("racer_assigned_motor_top_3_percent")),
            boat_number    = _int(d.get("racer_assigned_boat_number")),
            boat_in2_rate  = _float(d.get("racer_assigned_boat_top_2_percent")),
            boat_in3_rate  = _float(d.get("racer_assigned_boat_top_3_percent")),
        )


# ──────────────────────────────────────────
# 出走表エントリ（1艇分）
# ──────────────────────────────────────────

@dataclass
class RaceEntry:
    """
    1レースの出走枠（1艇分）。
    艇番・選手情報・モーター情報をまとめる。
    """
    boat_number: int
    course_number: int
    racer: RacerProfile
    motor_boat: MotorBoat

    @property
    def is_inner_course(self) -> bool:
        return self.course_number <= 3

    @classmethod
    def from_dict(cls, d: dict) -> RaceEntry:
        boat_no = _int(d.get("racer_boat_number"))
        return cls(
            boat_number   = boat_no,
            course_number = boat_no,
            racer         = RacerProfile.from_dict(d),
            motor_boat    = MotorBoat.from_dict(d),
        )


# ──────────────────────────────────────────
# 天候・水面状況
# ──────────────────────────────────────────

@dataclass
class WeatherInfo:
    """
    開催時の天候・水面状況。
    programs / results / previews 共通。
    """
    weather: str
    wind_direction: str
    wind_speed: int
    wave_height: int
    air_temperature: float
    water_temperature: float

    @classmethod
    def from_dict(cls, d: dict) -> WeatherInfo:
        weather_num  = d.get("weather_number")
        wind_dir_num = d.get("wind_direction_number")
        return cls(
            weather           = WEATHER_MAP.get(
                                    _int(weather_num), "不明"
                                ) if weather_num is not None else "不明",
            wind_direction    = WIND_DIR_MAP.get(
                                    _int(wind_dir_num), "不明"
                                ) if wind_dir_num is not None else "不明",
            wind_speed        = _int(d.get("wind_speed")),
            wave_height       = _int(d.get("wave_height")),
            air_temperature   = _float(d.get("air_temperature")),
            water_temperature = _float(d.get("water_temperature")),
        )

    @classmethod
    def empty(cls) -> WeatherInfo:
        return cls(
            weather="不明", wind_direction="不明",
            wind_speed=0, wave_height=0,
            air_temperature=0.0, water_temperature=0.0,
        )

    @property
    def wind_effect(self) -> str:
        """風速・風向きからインコースへの影響コメントを返す。"""
        if self.wind_speed == 0:
            return "無風（影響なし）"
        if self.wind_speed <= 2:
            return f"{self.wind_direction} {self.wind_speed}m（影響小）"
        if self.wind_speed <= 4:
            return f"{self.wind_direction} {self.wind_speed}m（影響中）"
        return f"{self.wind_direction} {self.wind_speed}m（影響大・荒れ注意）"


# ──────────────────────────────────────────
# 直前情報（展示タイム・スタート展示）
# ──────────────────────────────────────────

@dataclass
class ExhibitionInfo:
    """
    直前情報（展示タイム・スタートタイミング・チルト）。
    previews の boats{} から取得。
    """
    boat_number: int
    course_number: Optional[int]
    exhibition_time: float
    start_timing: Optional[float]
    tilt: float

    @classmethod
    def from_dict(cls, boat_no: int, d: dict) -> ExhibitionInfo:
        course = d.get("racer_course_number")
        st     = d.get("racer_start_timing")
        return cls(
            boat_number     = _int(d.get("racer_boat_number"), boat_no),
            course_number   = _int(course) if course is not None else None,
            exhibition_time = _float(d.get("racer_exhibition_time")),
            start_timing    = _float(st) if st is not None else None,
            tilt            = _float(d.get("racer_tilt_adjustment")),
        )


# ──────────────────────────────────────────
# レース番組（1レース分の全情報）
# ──────────────────────────────────────────

@dataclass
class RaceProgram:
    """
    1レース分の出走表データ。予測モデルへの入力となるメインのデータクラス。
    """
    stadium_number: int
    venue_id: str
    venue_name: str
    race_number: int
    race_date: str
    grade_label: str
    title: str
    distance: int
    entries: list[RaceEntry]
    weather: WeatherInfo
    exhibitions: list[ExhibitionInfo] = field(default_factory=list)

    @property
    def entry_by_boat(self) -> dict[int, RaceEntry]:
        return {e.boat_number: e for e in self.entries}

    @property
    def entry_by_course(self) -> dict[int, RaceEntry]:
        return {e.course_number: e for e in self.entries}

    @property
    def pole_entry(self) -> Optional[RaceEntry]:
        """1コース（イン）の選手エントリ。"""
        return self.entry_by_course.get(1)

    @property
    def race_id(self) -> str:
        """一意なレースID。例: '20260504_24_8'"""
        date_str = self.race_date.replace("-", "")
        return f"{date_str}_{self.venue_id}_{self.race_number}"


# ──────────────────────────────────────────
# レース結果（1レース分）
# ──────────────────────────────────────────

@dataclass
class RaceResult:
    """
    1レースの結果データ。results API から取得。
    未確定レース（中止・順延・null埋め）は from_dict() が None を返す。
    """
    stadium_number: int
    venue_id: str
    venue_name: str
    race_number: int
    race_date: str
    technique: str
    finishing_order: list[int]
    start_timings: dict[int, float]
    trifecta_combination: str
    trifecta_amount: int
    exacta_combination: str
    exacta_amount: int

    @property
    def race_id(self) -> str:
        date_str = self.race_date.replace("-", "")
        return f"{date_str}_{self.venue_id}_{self.race_number}"

    @property
    def winner_boat(self) -> int:
        return self.finishing_order[0] if self.finishing_order else 0

    @property
    def is_valid(self) -> bool:
        """有効なレース結果かどうか（中止・未確定でないか）。"""
        return bool(self.trifecta_combination and self.finishing_order)

    @classmethod
    def from_dict(cls, d: dict) -> Optional[RaceResult]:
        """
        dict から RaceResult を生成する。

        未確定レース（全フィールドが null）の場合は None を返す。
        呼び出し元で None チェックをすること。
        """
        # ── 未確定レース判定 ──────────────────────────
        # trifecta が空 かつ boats の racer_number が全て null
        # → 中止・順延・まだ結果未入力のレース
        payouts   = d.get("payouts", {})
        trifecta_list = payouts.get("trifecta", [])
        boats     = d.get("boats", [])

        all_null = all(
            b.get("racer_number") is None for b in boats
        )
        if all_null and not trifecta_list:
            return None   # 未確定レースはスキップ

        # ── 場情報 ────────────────────────────────────
        stadium_no = _int(d.get("stadium_number"))
        venue_name, venue_id = STADIUM_MAP.get(
            stadium_no,
            (f"場{stadium_no}", str(stadium_no).zfill(2))
        )

        # ── 着順 ──────────────────────────────────────
        # racer_place_number でソートして finishing_order を作成
        valid_boats = [b for b in boats if b.get("racer_place_number") is not None]
        sorted_boats = sorted(
            valid_boats,
            key=lambda b: _int(b.get("racer_place_number"), 99)
        )
        finishing_order = [_int(b.get("racer_boat_number")) for b in sorted_boats]

        # ── スタートタイミング ─────────────────────────
        start_timings = {
            _int(b.get("racer_boat_number")):
            _float(b.get("racer_start_timing"))
            for b in boats
            if b.get("racer_boat_number") is not None
        }

        # ── 払戻金 ────────────────────────────────────
        exacta_list = payouts.get("exacta", [])
        trifecta    = trifecta_list[0] if trifecta_list else {}
        exacta      = exacta_list[0]   if exacta_list   else {}

        technique_no = d.get("technique_number")

        return cls(
            stadium_number       = stadium_no,
            venue_id             = venue_id,
            venue_name           = venue_name,
            race_number          = _int(d.get("number")),
            race_date            = _str(d.get("date")),
            technique            = TECHNIQUE_MAP.get(
                                       _int(technique_no), "不明"
                                   ) if technique_no is not None else "不明",
            finishing_order      = finishing_order,
            start_timings        = start_timings,
            trifecta_combination = _str(trifecta.get("combination")),
            trifecta_amount      = _int(trifecta.get("amount")),
            exacta_combination   = _str(exacta.get("combination")),
            exacta_amount        = _int(exacta.get("amount")),
        )


# ──────────────────────────────────────────
# 競艇場設定（config/venues.yml と対応）
# ──────────────────────────────────────────

@dataclass
class VenueConfig:
    """会場設定（config/venues.yml の1エントリに対応）"""
    stadium_number: int
    id: str
    name: str
    location: str
    water_type: str          # sea / fresh
    opening_type: str        # day / night / midnight
    in_course_win_rate: float
    article_price: int
    hashtags: list[str]
    name_kana: str = ""
    characteristics: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "VenueConfig":
        return cls(
            stadium_number=_int(d.get("stadium_number")),
            id=_str(d.get("id", "")),
            name=_str(d.get("name", "")),
            name_kana=_str(d.get("name_kana", "")),
            location=_str(d.get("location", "")),
            water_type=_str(d.get("water_type", "sea")),
            opening_type=_str(d.get("opening_type", "day")),
            in_course_win_rate=_float(d.get("in_course_win_rate", 0.55)),
            article_price=_int(d.get("article_price", 500)),
            hashtags=list(d.get("hashtags", [])),
            characteristics=list(d.get("characteristics", [])),
        )

    @property
    def venue_name(self) -> str:
        return self.name

