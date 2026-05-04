"""
記事生成モジュール動作確認スクリプト
"""
import logging
import sys
from pathlib import Path

# ── プロジェクトルートを sys.path に追加 ──────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── .env 読み込み（必ず最初に実行） ──────────────────────────────
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# ── ここから通常の import ─────────────────────────────────────────
import os
from datetime import date, timedelta

from src.data.boatrace_api import BoatraceAPIClient
from src.prediction.feature_builder import FeatureBuilder
from src.prediction.rule_based import RuleBasedPredictor
from src.generation.article_generator import ArticleGenerator
from src.generation.x_post_generator import XPostGenerator

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    yesterday = date.today() - timedelta(days=1)
    stadium_number = 1      # 桐生（確実にデータがある会場）
    race_number = 1         # 1R

    # ── データ取得 ────────────────────────────────────────────────
    api = BoatraceAPIClient(cache_dir=ROOT / "data" / "raw")

    # 正しい引数順: (dt, stadium_number)
    races = api.get_venue_races(yesterday, stadium_number)
    if not races:
        logger.error(
            "レースデータが取得できませんでした (stadium=%d, date=%s)",
            stadium_number, yesterday,
        )
        sys.exit(1)

    race = next((r for r in races if r.race_number == race_number), races[0])
    logger.info(
        "対象レース: %dR %s %s",
        race.race_number, race.venue_name, race.grade_label,
    )

    # ── 特徴量 & 予測 ─────────────────────────────────────────────
    builder = FeatureBuilder()
    features = builder.build(race)

    predictor = RuleBasedPredictor()
    prediction = predictor.predict(features)
    logger.info(
        "予測完了: %dR 本命=%s 信頼度=%s",
        race.race_number, prediction.honmei.racer_name, prediction.confidence,
    )

    # ── 記事生成 ──────────────────────────────────────────────────
    logger.info("記事生成開始...")
    generator = ArticleGenerator()
    result = generator.generate(race=race, prediction=prediction)

    print("\n" + "=" * 60)
    print(f"【タイトル】{result.title}")
    print("=" * 60)
    print(f"【無料部分】({len(result.free_md)} 文字)")
    print(result.free_md[:300], "..." if len(result.free_md) > 300 else "")
    print("-" * 40)
    print(f"【有料部分冒頭】({len(result.paid_md)} 文字)")
    print(result.paid_md[:300], "..." if len(result.paid_md) > 300 else "")
    print("-" * 40)
    print(f"【ハッシュタグ】{result.hashtags}")
    print(f"【価格】¥{result.price}")

        # ── X 投稿文生成 ──────────────────────────────────────────────
    logger.info("X投稿文生成開始...")
    x_gen = XPostGenerator()

    import yaml
    from src.data.models import VenueConfig

    venues_cfg = yaml.safe_load(
        (ROOT / "config" / "venues.yml").read_text(encoding="utf-8")
    )
    venue_list = venues_cfg.get("venues", [])

    venue_raw = next(
        (v for v in venue_list if int(v.get("stadium_number", -1)) == stadium_number),
        None,
    )
    logger.info("venues.yml から取得: %s", venue_raw.get("name") if venue_raw else "None→フォールバック")

    venue_config = (
        VenueConfig.from_dict(venue_raw)
        if venue_raw
        else VenueConfig(
            stadium_number=stadium_number,
            id=f"{stadium_number:02d}",
            name="桐生",
            location="群馬県",
            water_type="fresh",
            opening_type="day",
            in_course_win_rate=0.55,
            article_price=500,
            hashtags=["桐生", "競艇"],
        )
    )

    x_post = x_gen.generate(
        prediction=prediction,
        venue_config=venue_config,
        note_url="https://note.com/notes/test_dummy_key",
    )
    print("\n" + "=" * 60)
    print(f"【X投稿文】({len(x_post)} 文字)")
    print(x_post)
    print("=" * 60)




if __name__ == "__main__":
    main()
