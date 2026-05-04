"""
Gemini API クライアント (google-genai SDK v1.x 対応)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class GeminiClient:
    """google-genai SDK を使った Gemini / Gemma モデルラッパー"""

    DEFAULT_MODEL = "gemma-4-26b-a4b-it"
    FALLBACK_MODEL = "gemini-2.0-flash"
    RETRY_COUNT = 3
    RETRY_WAIT = 5  # seconds

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY が設定されていません")

        self.model = model or os.environ.get("GEMINI_MODEL", self.DEFAULT_MODEL)
        self._client = genai.Client(api_key=self.api_key)
        logger.info("GeminiClient 初期化完了: model=%s", self.model)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def generate(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_output_tokens: int = 4096,
    ) -> str:
        """テキスト生成（リトライあり）"""
        config = self._build_config(system_prompt, temperature, max_output_tokens)
        last_error: Optional[Exception] = None

        for attempt in range(1, self.RETRY_COUNT + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=config,
                )
                text = self._extract_text(response)
                logger.debug(
                    "生成完了: attempt=%d, chars=%d", attempt, len(text)
                )
                return text

            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "生成エラー (attempt %d/%d): %s",
                    attempt,
                    self.RETRY_COUNT,
                    exc,
                )
                if attempt < self.RETRY_COUNT:
                    time.sleep(self.RETRY_WAIT * attempt)

        raise RuntimeError(
            f"Gemini API リトライ上限到達: {last_error}"
        ) from last_error

    def generate_with_fallback(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_output_tokens: int = 4096,
    ) -> str:
        """
        メインモデルで失敗した場合 FALLBACK_MODEL (gemini-2.0-flash) で再試行する。
        """
        try:
            return self.generate(
                user_prompt, system_prompt, temperature, max_output_tokens
            )
        except RuntimeError as exc:
            logger.warning(
                "メインモデル失敗 → フォールバック (%s): %s",
                self.FALLBACK_MODEL,
                exc,
            )
            original_model = self.model
            self.model = self.FALLBACK_MODEL
            try:
                return self.generate(
                    user_prompt, system_prompt, temperature, max_output_tokens
                )
            finally:
                self.model = original_model  # 元に戻す

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_config(
        self,
        system_prompt: Optional[str],
        temperature: float,
        max_output_tokens: int,
    ) -> types.GenerateContentConfig:
        kwargs: dict = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "safety_settings": [
                types.SafetySetting(
                    category="HARM_CATEGORY_HARASSMENT",
                    threshold="BLOCK_NONE",
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_HATE_SPEECH",
                    threshold="BLOCK_NONE",
                ),
            ],
        }
        if system_prompt:
            kwargs["system_instruction"] = system_prompt
        return types.GenerateContentConfig(**kwargs)

    @staticmethod
    def _extract_text(response) -> str:  # noqa: ANN001
        """レスポンスオブジェクトからテキストを安全に取り出す"""
        try:
            return response.text or ""
        except (AttributeError, ValueError):
            pass
        # candidates フォールバック
        try:
            parts = response.candidates[0].content.parts
            return "".join(p.text for p in parts if hasattr(p, "text"))
        except (IndexError, AttributeError):
            return ""
