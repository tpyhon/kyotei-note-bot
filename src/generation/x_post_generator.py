"""
X（Twitter）投稿文生成モジュール
"""
from __future__ import annotations

import logging
from typing import Optional

from src.data.models import VenueConfig
from src.generation.gemini_client import GeminiClient
from src.prediction.rule_based import Prediction

logger = logging.getLogger(__name__)

_X_MAX_CHARS = 140


class XPostGenerator:
    @staticmethod
    def _combo_str(combination) -> str:
        """
        combination が str の場合はそのまま返す。
        list/tuple の場合は "-" で結合する。
        例: "1-3-5" → "1-3-5" / [1,3,5] → "1-3-5"
        """
        if isinstance(combination, str):
            return combination
        return "-".join(str(c) for c in combination)
    """Prediction + VenueConfig → X投稿文（140文字以内）を生成する"""

    def __init__(self, gemini_client: Optional[GeminiClient] = None) -> None:
        self.gemini = gemini_client or GeminiClient()

    # ------------------------------------------------------------------ #
    #  Public                                                              #
    # ------------------------------------------------------------------ #

    def generate(
        self,
        prediction: Prediction,
        venue_config: VenueConfig,
        note_url: str,
    ) -> str:
        """
        X投稿文を生成して返す（140文字超の場合はフォールバック文を使用）。

        Args:
            prediction : RuleBasedPredictor が生成した予測オブジェクト
            venue_config: 会場設定（venues.yml の1エントリ）
            note_url    : 公開済み Note 記事の URL
        Returns:
            140文字以内のX投稿文字列
        """
        try:
            post = self._generate_with_gemini(prediction, venue_config, note_url)
            if len(post) <= _X_MAX_CHARS:
                logger.info("X投稿文生成完了: %d文字", len(post))
                return post
            logger.warning(
                "生成文が%d文字超 → フォールバック使用", _X_MAX_CHARS
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini X投稿生成失敗 → フォールバック: %s", exc)

        return self._fallback(prediction, venue_config, note_url)

    # ------------------------------------------------------------------ #
    #  Private                                                             #
    # ------------------------------------------------------------------ #

    def _generate_with_gemini(
        self,
        prediction: Prediction,
        venue_config: VenueConfig,
        note_url: str,
    ) -> str:
        system_prompt = (
            "あなたは競艇リポーター「波乃みなと」です。"
            "明るく元気で親しみやすい口調で、競艇予想記事のX（Twitter）告知文を書いてください。"
            "140文字以内に必ず収めること。URLは含めないこと（後から追加します）。"
            "絵文字を1〜2個使うと読者に喜ばれます。"
        )

        confidence_map = {"高": "🔥自信あり", "中": "⚡注目", "低": "💡穴狙い"}
        confidence_str = confidence_map.get(prediction.confidence, "⚡注目")

        # bet_type 日本語変換
        _BET_TYPE_JP = {
            "trifecta": "3連単",
            "exacta": "2連単",
            "trio": "3連複",
            "quinella": "2連複",
        }
        buy_summary = ""
        if prediction.buy_targets:
            top = prediction.buy_targets[0]
            combo = self._combo_str(top.combination)   # ← 修正
            bet_jp = _BET_TYPE_JP.get(top.bet_type, top.bet_type)
            buy_summary = f"{bet_jp} {combo}"



        user_prompt = (
            f"以下のデータをもとに、競艇予想のX告知文を140文字以内で書いてください。\n\n"
            f"会場: {venue_config.name}\n"
            f"レース: {prediction.honmei.boat_number}号艇 {prediction.honmei.racer_name} 本命\n"
            f"信頼度: {confidence_str}\n"
            f"注目買い目: {buy_summary}\n\n"
            f"URLは含めないでください。文末に「詳細はnoteで！」という一言を入れてください。"
        )

        text = self.gemini.generate(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.8,
            max_output_tokens=256,
        )
        # URLを末尾に付与
        post = f"{text.strip()}\n{note_url}"
        return post

    def _fallback(
        self,
        prediction: Prediction,
        venue_config: VenueConfig,
        note_url: str,
    ) -> str:
        confidence_emoji = {"高": "🔥", "中": "⚡", "低": "💡"}.get(
            prediction.confidence, "⚡"
        )

        # bet_type 日本語変換
        _BET_TYPE_JP = {
            "trifecta": "3連単",
            "exacta": "2連単",
            "trio": "3連複",
            "quinella": "2連複",
        }

        buy_str = ""
        if prediction.buy_targets:
            top = prediction.buy_targets[0]
            combo = self._combo_str(top.combination)   # ← 修正
            bet_jp = _BET_TYPE_JP.get(top.bet_type, top.bet_type)
            buy_str = f"注目買い目: {bet_jp} {combo}\n"


        post = (
            f"{confidence_emoji}【{venue_config.name}競艇 予想】\n"
            f"本命: {prediction.honmei.boat_number}号艇"
            f" {prediction.honmei.racer_name}\n"
            f"{buy_str}"
            f"詳細はnoteで！\n{note_url}"
        )

        # 140文字超の場合はさらに短縮
        if len(post) > 140:
            post = (
                f"{confidence_emoji}{venue_config.name}"
                f" {prediction.honmei.boat_number}号艇"
                f"{prediction.honmei.racer_name}本命🎯\n"
                f"{note_url}"
            )
        return post

