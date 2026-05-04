import requests, json
from datetime import date, timedelta

yesterday = date.today() - timedelta(days=1)
url = 'https://boatraceopenapi.github.io/results/v3/{}/{}.json'.format(
    yesterday.year, yesterday.strftime('%Y%m%d')
)
data = requests.get(url).json()
results = data.get('results', [])

# Noneが含まれているレースを探す
for r in results[:50]:
    payouts = r.get('payouts', {})
    trifecta = payouts.get('trifecta', [])
    # trifectaが空のレースを探す
    if not trifecta:
        print('=== trifecta空のレース ===')
        print(json.dumps(r, ensure_ascii=False, indent=2))
        break

# technique_numberがNoneのレースを探す
for r in results[:50]:
    if r.get('technique_number') is None:
        print('=== technique_number=None のレース（最初の1件） ===')
        print('stadium={} number={} technique_number={}'.format(
            r.get('stadium_number'), r.get('number'), r.get('technique_number')
        ))
        print('boats[0]:', json.dumps(r.get('boats', [])[0], ensure_ascii=False))
        break
