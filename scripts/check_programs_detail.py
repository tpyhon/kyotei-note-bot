import requests, json
from datetime import date, timedelta

# programsは今日が404だったので直近で取得できる日を探す
import datetime

for days_back in range(1, 8):
    target = date.today() - datetime.timedelta(days=days_back)
    url = 'https://boatraceopenapi.github.io/programs/v3/{}/{}.json'.format(
        target.year, target.strftime('%Y%m%d')
    )
    resp = requests.get(url)
    print('GET {} -> {}'.format(url, resp.status_code))
    if resp.status_code == 200:
        data = resp.json()
        print('トップレベルキー:', list(data.keys()))
        programs = data.get('programs', data.get('races', []))
        if programs:
            print('programs[0] のキー:', list(programs[0].keys()))
            p0 = programs[0]
            # boatsキーの中身を確認
            boats = p0.get('boats', p0.get('players', p0.get('entries', [])))
            if boats:
                # リストか辞書かも確認
                print('boats の型:', type(boats).__name__)
                if isinstance(boats, list):
                    print('boats[0] のキー:', list(boats[0].keys()))
                    print('boats[0] 全フィールド:')
                    print(json.dumps(boats[0], ensure_ascii=False, indent=2))
                elif isinstance(boats, dict):
                    first_key = list(boats.keys())[0]
                    print('boats[\"{}\"] 全フィールド:'.format(first_key))
                    print(json.dumps(boats[first_key], ensure_ascii=False, indent=2))
            print('\\nprogram[0] boats以外のフィールド:')
            no_boats = {k: v for k, v in p0.items() if k not in ('boats','players','entries')}
            print(json.dumps(no_boats, ensure_ascii=False, indent=2))
        break
