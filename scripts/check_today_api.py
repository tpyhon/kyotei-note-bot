import requests
from datetime import date

today = date.today()
date_str = today.strftime("%Y%m%d")
url = f"https://boatraceopenapi.github.io/programs/v3/{today.year}/{date_str}.json"
resp = requests.get(url)
print(f"today={today} status={resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    programs = data.get("programs", [])
    print(f"race_count={len(programs)}")
    if programs:
        p = programs[0]
        print(f"first: date={p.get('date')} stadium={p.get('stadium_number')} race={p.get('number')}")
else:
    print("no data yet")
