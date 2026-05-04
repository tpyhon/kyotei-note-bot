import sys, os, logging
sys.path.insert(0, '.')
logging.basicConfig(level='INFO', format='%(asctime)s [%(levelname)s] %(message)s')

from datetime import timedelta
from pathlib import Path
from src.data.boatrace_api import BoatraceAPIClient
from src.data.models import VenueConfig
from src.prediction.feature_builder import FeatureBuilder
from src.prediction.rule_based import RuleBasedPredictor
import yaml

client    = BoatraceAPIClient(cache_dir=Path('data/raw'))
yesterday = client.yesterday()

# 桐生（1番）で動作確認
races = client.get_venue_races(yesterday, stadium_number=1)
if not races:
    print('データなし')
    exit()

# venues.ymlから大村の設定を読む（桐生はないのでNoneで代用）
builder   = FeatureBuilder(venue_config=None)
predictor = RuleBasedPredictor()

race = races[0]
print('=== {}R {} {} ==='.format(race.race_number, race.venue_name, race.grade_label))

features   = builder.build(race)
prediction = predictor.predict(features)

print('本命: {}コース {} ({}) {:.1f}pt'.format(
    prediction.honmei.course_number,
    prediction.honmei.racer_name,
    prediction.honmei.grade,
    prediction.honmei.total_score,
))
print('対抗: {}コース {} ({}) {:.1f}pt'.format(
    prediction.taikou.course_number,
    prediction.taikou.racer_name,
    prediction.taikou.grade,
    prediction.taikou.total_score,
))
if prediction.ana:
    print('穴  : {}コース {} ({}) {:.1f}pt'.format(
        prediction.ana.course_number,
        prediction.ana.racer_name,
        prediction.ana.grade,
        prediction.ana.total_score,
    ))
print('信頼度: {} - {}'.format(prediction.confidence, prediction.confidence_reason))
print('買い目:')
for b in prediction.buy_targets:
    print('  [{}] {} ({})'.format(b.bet_type[:3], b.combination, b.reason))
