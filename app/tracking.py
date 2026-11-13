"""Read-only collectible presentation and age-filtered area progress."""
from collections import defaultdict
import math
import re

from core import collected

AGES = ('Child', 'Adult')
AGE_FILTERS = ('All', 'Child', 'Adult', 'Unknown')


def decorate_catalog(items):
    ages = defaultdict(set)
    for item in items:
        key = item['kind'], item['id']
        explicit = item.get('ages', [])
        if not isinstance(explicit, list) or any(age not in AGES for age in explicit):
            raise ValueError('Invalid collectible age metadata')
        ages[key].update(explicit)
        match = re.search(r'_(Child|Adult)(?:_|$)', item['area'])
        if match:
            ages[key].add(match[1])
    return [dict(item, ages=[age for age in AGES if age in ages[item['kind'], item['id']]],
                 region=re.sub(r'_(?:Child|Adult)(?:_Alternative)?$', '', item['area']))
            for item in items]


def height_text(delta, compact=False):
    if not math.isfinite(delta):
        raise ValueError('Collectible height difference is invalid')
    if abs(delta) < 0.5:
        return '0m' if compact else '0 m level'
    if compact:
        return f'{delta:+.0f}m'
    return f"{delta:+.0f} m {'up' if delta > 0 else 'down'}"


def age_text(item, compact=False):
    ages = item.get('ages', [])
    if not ages:
        return 'Age ?' if compact else 'Age availability: not specified by game map'
    return ('/'.join(ages) if compact else 'Available: ' + ' / '.join(ages) + ' Link')


def target_caption(item, near=False):
    name = 'Skulltula' if item['kind'] == 'skull' else 'Heart piece'
    prefix = f'{name} nearby' if near else f'Nearest {name.lower()}'
    return f"{prefix}: {item['distance']:.0f} m | {height_text(item['dy'])}\n{age_text(item)}"


def area_progress(catalog, save, age='All'):
    if age not in AGE_FILTERS:
        raise ValueError('Invalid progress age filter')
    groups, all_items = {}, {'skull': {}, 'heart': {}}
    for item in catalog:
        available = item.get('ages', [])
        if age == 'Unknown' and available or age in AGES and age not in available:
            continue
        region = item['region']
        group = groups.setdefault(region, {'skull': {}, 'heart': {}})
        kind, key, found = item['kind'], item['id'], collected(item, save)
        group[kind][key] = group[kind].get(key, False) or found
        all_items[kind][key] = all_items[kind].get(key, False) or found

    def count(values):
        return sum(values.values()), len(values)

    rows = [dict(region=region, label=re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', region),
                 **{kind: count(values) for kind, values in groups[region].items()})
            for region in sorted(groups)]
    return rows, {kind: count(values) for kind, values in all_items.items()}
