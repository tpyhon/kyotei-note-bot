"""
記事生成モジュール – Gemini API を使って Note 記事 Markdown を生成する
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.data.models import RaceProgram
from src.generation.gemini_client import GeminiClient
from src.prediction.rule_based import Prediction

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("プロンプトファイルが見つかりません: %s", path)
    return ""


@dataclass
class ArticleResult:
    title: str
    free_md: str
    paid_md: str
    full_md: str
    hashtags: list[str]
    price: int


class ArticleGenerator:
    """RaceProgram + Prediction → Note記事Markdown を生成する"""

    DEFAULT_HASHTAGS = ["競艇", "競艇予想", "ボートレース", "ボートレース予想"]
    DEFAULT_PRICE = 500

    def __init__(self, gemini_client: Optional[GeminiClient] = None) -> None:
        self.gemini = gemini_client or GeminiClient()
        self._system_prompt = _load_prompt("article_system.txt")
        self._user_template = _load_prompt("article_user.txt")

    # ------------------------------------------------------------------ #
    #  Public                                                              #
    # ------------------------------------------------------------------ #

    def generate(
        self,
        race: RaceProgram,
        prediction: Prediction,
        price: int = DEFAULT_PRICE,
        extra_hashtags: Optional[list[str]] = None,
    ) -> ArticleResult:
        input_text = self._build_input_data(race, prediction)

        if self._user_template and "{{INPUT_DATA}}" in self._user_template:
            user_prompt = self._user_template.replace("{{INPUT_DATA}}", input_text)
        else:
            user_prompt = input_text

        logger.info(
            "Gemini 記事生成リクエスト: %dR %s",
            race.race_number, race.venue_name,
        )
        raw_text = self.gemini.generate_with_fallback(
            user_prompt=user_prompt,
            system_prompt=self._system_prompt or None,
            temperature=0.75,
            max_output_tokens=4096,
        )
        logger.info("Gemini 生成完了: %d 文字", len(raw_text))

        title = self._build_title(race, prediction)
        free_md, paid_md = self._split_sections(raw_text)
        hashtags = self._build_hashtags(race, extra_hashtags)

        return ArticleResult(
            title=title,
            free_md=free_md,
            paid_md=paid_md,
            full_md=raw_text,
            hashtags=hashtags,
            price=price,
        )

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_input_data(self, race: RaceProgram, prediction: Prediction) -> str:
        """予測データを Gemini への入力テキストに変換する"""
        lines: list[str] = []

        # ── 基本情報 ──────────────────────────────────────────────
        lines.append("## レース基本情報")
        lines.append(f"- 開催場: {race.venue_name}（場コード {race.stadium_number}）")
        lines.append(f"- レース番号: {race.race_number}R")
        lines.append(f"- グレード: {race.grade_label}")
        lines.append(f"- タイトル: {race.title or '一般戦'}")
        lines.append(f"- 距離: {race.distance}m")
        lines.append(f"- 日付: {race.race_date}")          # ← race.date → race.race_date
        lines.append("")

        # ── 天候情報 ──────────────────────────────────────────────
        w = race.weather
        lines.append("## 天候・水面状況")
        lines.append(f"- 天候: {w.weather}")
        lines.append(f"- 風向: {w.wind_direction}  風速: {w.wind_speed}m/s")
        lines.append(f"- 波高: {w.wave_height}cm")
        lines.append(f"- 気温: {w.air_temperature}℃  水温: {w.water_temperature}℃")
        lines.append("")

        # ── 出走艇データ ──────────────────────────────────────────
        lines.append("## 出走艇データ")
        for entry in race.entries:
            r = entry.racer          # RacerProfile
            mb = entry.motor_boat    # MotorBoat
            lines.append(
                f"- {entry.boat_number}号艇（{entry.course_number}コース）"
                f" {r.name}（{r.grade}）"
                f" 全国勝率{r.national_win_rate:.2f}"
                f" / 地元勝率{r.local_win_rate:.2f}"
                f" / モーター2連率{mb.motor_in2_rate:.1f}%"
                f" / 平均ST{r.avg_start_timing:.2f}"
                f" / F{r.flying_count}L{r.late_count}"
            )
        lines.append("")

        # ── 展示情報 ──────────────────────────────────────────────
        if race.exhibitions:
            lines.append("## 展示タイム")
            for ex in race.exhibitions:
                lines.append(
                    f"- {ex.boat_number}号艇"
                    f" 展示タイム{ex.exhibition_time:.2f}"
                    f" / コース{ex.course_number}"
                    f" / ST{ex.start_timing:.2f}"
                    f" / チルト{ex.tilt:.1f}"
                )
            lines.append("")

        # ── 予測結果 ──────────────────────────────────────────────
        lines.append("## 予測結果")
        lines.append(
            f"- 本命: {prediction.honmei.boat_number}号艇"
            f" {prediction.honmei.racer_name}"
            f"（スコア {prediction.honmei.total_score:.1f}pt）"
        )
        lines.append(
            f"- 対抗: {prediction.taikou.boat_number}号艇"
            f" {prediction.taikou.racer_name}"
            f"（スコア {prediction.taikou.total_score:.1f}pt）"
        )
        if prediction.ana:
            lines.append(
                f"- 穴: {prediction.ana.boat_number}号艇"
                f" {prediction.ana.racer_name}"
                f"（スコア {prediction.ana.total_score:.1f}pt）"
            )
        lines.append(f"- 信頼度: {prediction.confidence}")
        lines.append(f"- 信頼度メモ: {prediction.confidence_reason}")
        lines.append("")

        # ── 買い目 ────────────────────────────────────────────────
        lines.append("## 推奨買い目")
        for bt in prediction.buy_targets:
            # combination が str の場合はそのまま、list の場合は結合
            combo_str = bt.combination if isinstance(bt.combination, str) \
                else "-".join(str(c) for c in bt.combination)
            lines.append(
                f"- {bt.bet_type} {combo_str}"
                f"（優先度: {bt.priority}、理由: {bt.reason}）"
            )


        return "\n".join(lines)

    def _build_title(self, race: RaceProgram, prediction: Prediction) -> str:
        confidence_emoji = {"高": "🔥", "中": "⚡", "低": "💡"}.get(
            prediction.confidence, "⚡"
        )
        return (
            f"{confidence_emoji}【{race.venue_name} {race.race_number}R】"
            f"{prediction.honmei.racer_name} 本命予想｜"
            f"波乃みなとの競艇GOGO!"
        )

    def _split_sections(self, raw_text: str) -> tuple[str, str]:
        # 1. タグ方式
        if "[FREE_START]" in raw_text and "[PAID_START]" in raw_text:
            free_md = self._extract_between(raw_text, "[FREE_START]", "[FREE_END]")
            paid_md = self._extract_between(raw_text, "[PAID_START]", "[PAID_END]")
            if free_md and paid_md:
                return free_md.strip(), paid_md.strip()

        # 2. 区切り線方式
        if "\n---\n" in raw_text:
            parts = raw_text.split("\n---\n", 1)
            return parts[0].strip(), parts[1].strip()

        # 3. フォールバック: 前半40%を無料
        split_pos = max(200, int(len(raw_text) * 0.4))
        newline_pos = raw_text.rfind("\n\n", 0, split_pos)
        if newline_pos > 100:
            split_pos = newline_pos
        return raw_text[:split_pos].strip(), raw_text[split_pos:].strip()

    @staticmethod
    def _extract_between(text: str, start_tag: str, end_tag: str) -> str:
        start = text.find(start_tag)
        end = text.find(end_tag)
        if start == -1 or end == -1:
            return ""
        return text[start + len(start_tag):end]

    def _build_hashtags(
        self,
        race: RaceProgram,
        extra_hashtags: Optional[list[str]],
    ) -> list[str]:
        tags = list(self.DEFAULT_HASHTAGS) + [race.venue_name]
        if extra_hashtags:
            tags.extend(extra_hashtags)
        seen: set[str] = set()
        result: list[str] = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result
