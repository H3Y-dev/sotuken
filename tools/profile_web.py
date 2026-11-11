"""Repeatable isolated AppTest benchmark; never touches the live receiver or DB."""
import argparse
import cProfile
from contextlib import chdir
import io
import json
from pathlib import Path
import pstats
from statistics import median
import subprocess
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def measure(count, revision=None):
    from streamlit.testing.v1 import AppTest
    from streamlit.runtime.scriptrunner.script_runner import ScriptRunner
    from manager.storage import Storage
    profiles = []
    original = ScriptRunner._run_script
    def profiled_run(runner, *args, **kwargs):
        profile = cProfile.Profile()
        profiles.append(profile)
        return profile.runcall(original, runner, *args, **kwargs)
    with tempfile.TemporaryDirectory() as directory, chdir(directory):
        storage = Storage('manager.db')
        for index in range(count):
            storage.save_reading(f'Meter {index % 20}', f'photo-{index}.png', {
                'stage': 'ok', 'status': 'ok', 'value': index % 40,
                'device_id': f'meter-{index % 20}',
                'inspection_id': f'round-{index // 50}',
                'inspection_name': f'Round {index // 50}',
            })
        receiver = {'running': False, 'error': 'isolated benchmark'}
        with patch('manager.receiver.init_receiver_for_app', return_value=receiver), \
                patch.object(ScriptRunner, '_run_script', profiled_run):
            start = perf_counter()
            if revision:
                source = subprocess.run(['git', 'show', f'{revision}:app.py'], cwd=ROOT,
                    check=True, capture_output=True, encoding='utf-8').stdout
                source = source.replace('os.path.dirname(os.path.abspath(__file__))', repr(str(ROOT)))
                baseline = Path(directory) / 'baseline_app.py'
                baseline.write_text(source, encoding='utf-8')
                app = AppTest.from_file(str(baseline), default_timeout=120).run()
            else:
                app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=120).run()
            first = perf_counter() - start
            assert not app.exception, app.exception
            timings = {}
            warm = {}
            for page in ('点検', '機器'):
                start = perf_counter()
                if app.radio:
                    app.radio(key='page').set_value(page).run()
                else:
                    app.run()
                timings[page] = perf_counter() - start
                assert not app.exception, app.exception
            for page in ('点検', '機器'):
                samples = []
                for _ in range(3):
                    if app.radio:
                        app.radio(key='page').set_value('ホーム').run()
                    start = perf_counter()
                    if app.radio:
                        app.radio(key='page').set_value(page).run()
                    else:
                        app.run()
                    samples.append(perf_counter() - start)
                    assert not app.exception, app.exception
                warm[page] = median(samples)
            samples = []
            for checked in (True, False, True):
                start = perf_counter()
                next(c for c in app.checkbox if c.label == '自動更新(5秒ごと)').set_value(checked).run()
                samples.append(perf_counter() - start)
                assert not app.exception, app.exception
            rerun = median(samples)
            stream = io.StringIO()
            stats = pstats.Stats(profiles[0], stream=stream)
            for profile in profiles[1:]:
                stats.add(profile)
            stats.sort_stats('cumulative').print_stats(10)
            return {'rows': count, 'first_seconds': first,
                    'rerun_seconds': rerun, 'pages_seconds': timings,
                    'warm_pages_seconds': warm,
                    'top10': stream.getvalue()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows', type=int, default=300)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision', help='Benchmark app.py from a git revision instead of the working tree')
    args = parser.parse_args()
    result = [measure(0, args.revision), measure(args.rows, args.revision)]
    args.output.resolve().write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
