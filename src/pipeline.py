"""
メインパイプライン
データ取得 → 予測 → 記事生成 → Note投稿 → X告知
"""
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def main():
    # TODO: 実装予定
    logger.info("pipeline.main() が呼び出されました（未実装）")


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    main()
