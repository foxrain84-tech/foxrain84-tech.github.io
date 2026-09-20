"""Save read-only Firebase count snapshots. Fail closed; never overwrite on error."""
import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

URL = 'https://yulim-mood-prompt-archive-default-rtdb.firebaseio.com/copyCounts.json'
TARGET = Path(__file__).resolve().parents[1] / 'stats-history.json'
KST = ZoneInfo('Asia/Seoul')


def valid_counts(counts):
    return isinstance(counts, dict) and all(
        isinstance(key, str) and type(value) is int and 0 <= value <= 9007199254740991
        for key, value in counts.items())


def update_history(history, counts, at):
    if not valid_counts(counts):
        raise ValueError('Invalid counts; previous history preserved')
    if history.get('version') != 1 or not isinstance(history.get('days'), dict):
        raise ValueError('Invalid history; previous history preserved')
    for day, snapshot in history['days'].items():
        stamp = datetime.fromisoformat(snapshot['at'])
        if stamp.tzinfo is None or stamp.astimezone(KST).date().isoformat() != day or not valid_counts(snapshot['counts']):
            raise ValueError('Invalid stored snapshot')
    local = at.astimezone(KST)
    cutoff = (local.date() - timedelta(days=35)).isoformat()
    days = {day: snapshot for day, snapshot in history['days'].items() if day >= cutoff}
    days[local.date().isoformat()] = {'at': local.isoformat(), 'counts': counts}
    return {'version': 1, 'timezone': 'Asia/Seoul', 'days': days}


def main():
    history = json.loads(TARGET.read_text()) if TARGET.exists() else {'version': 1, 'days': {}}
    for attempt in range(3):
        try:
            with urlopen(URL, timeout=25) as response:
                counts = json.load(response)
            if counts is None:
                counts = {}
            if not valid_counts(counts):
                raise ValueError('Invalid Firebase response')
            break
        except Exception:
            if attempt == 2:
                raise RuntimeError('Statistics snapshot failed; existing history preserved') from None
            time.sleep(2 ** attempt)
    result = update_history(history, counts, datetime.now(KST))
    with tempfile.NamedTemporaryFile(mode='w', dir=TARGET.parent, delete=False, encoding='utf-8') as file:
        json.dump(result, file, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        file.write('\n')
        temporary = file.name
    os.replace(temporary, TARGET)
    print('Saved daily statistics snapshot (KST); no Firebase writes.')


if __name__ == '__main__':
    main()
