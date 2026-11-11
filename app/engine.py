import csv
import io
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, localcontext


def read_csv(text):
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    columns = reader.fieldnames
    if not columns or len(columns) != len(set(columns)) or any(not c.strip() for c in columns):
        raise ValueError('CSV needs unique, nonempty column headers.')
    rows = []
    for number, row in enumerate(reader, 2):
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f'Malformed CSV at line {number}.')
        rows.append({'id': number, 'values': row})
        if len(rows) > 50000:
            raise ValueError('Maximum 50,000 rows per file.')
    if not rows: raise ValueError('CSV contains no data rows.')
    return {'columns': columns, 'rows': rows}


def profile(data):
    return {'rows': len(data['rows']), 'columns': [
        {'name': c, 'empty': sum(not r['values'][c].strip() for r in data['rows']),
         'distinct': len(set(r['values'][c] for r in data['rows'])),
         'duplicate_values': sum(n-1 for v,n in Counter(r['values'][c] for r in data['rows']).items() if v.strip() and n>1),
         'samples': list(dict.fromkeys(r['values'][c] for r in data['rows']))[:5]}
        for c in data['columns']]}


def reconcile(left, right, recipe):
    lk, rk = recipe.get('left_key'), recipe.get('right_key')
    if lk not in left['columns'] or rk not in right['columns']:
        raise ValueError('Select an existing matching column from each file.')
    comparisons = recipe.get('comparisons', [])
    if not comparisons:
        raise ValueError('Add at least one comparison.')
    specs = []
    for c in comparisons:
        if c.get('left') not in left['columns'] or c.get('right') not in right['columns']:
            raise ValueError('Comparison references an unknown column.')
        kind = c.get('type', 'text')
        if kind not in ('text', 'number'):
            raise ValueError('Only text and number comparisons are supported.')
        try:
            tolerance = Decimal(str(c.get('tolerance', 0)))
            if not tolerance.is_finite() or tolerance < 0:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise ValueError('Tolerance must be a finite nonnegative number.')
        specs.append((c, kind, tolerance))
    def normalize(value):
        if recipe.get('trim', True): value = value.strip()
        if recipe.get('ignore_case', True): value = value.upper()
        return value
    indexes = []
    for data, key in ((left, lk), (right, rk)):
        index = defaultdict(list)
        for row in data['rows']: index[normalize(row['values'][key])].append(row)
        indexes.append(index)
    li, ri = indexes
    results = []
    for key in sorted(set(li) | set(ri)):
        ls, rs = li.get(key, []), ri.get(key, [])
        status, details = '', []
        if not key.strip(): status = 'invalid_key'
        elif len(ls) > 1 or len(rs) > 1: status = 'duplicate_key'
        elif not ls: status = 'right_only'
        elif not rs: status = 'left_only'
        else:
            invalid = False
            for c, kind, tolerance in specs:
                a, b = ls[0]['values'][c['left']], rs[0]['values'][c['right']]
                difference = None
                if kind == 'number':
                    try:
                        av, bv = Decimal(a.strip()), Decimal(b.strip())
                        if not av.is_finite() or not bv.is_finite() or any(len(v.as_tuple().digits)>100 or abs(v.as_tuple().exponent)>100 for v in (av,bv)): raise InvalidOperation()
                        with localcontext() as context:
                            context.prec = 220
                            difference = str(av - bv)
                            equal = abs(av - bv) <= tolerance
                    except InvalidOperation:
                        invalid = True
                        equal = False
                else: equal = normalize(a) == normalize(b)
                if not equal:
                    details.append({'left_column': c['left'], 'right_column': c['right'],
                                    'left': a, 'right': b, 'difference': difference,
                                    'reason': 'invalid_number' if kind == 'number' and difference is None else 'different'})
            status = 'invalid_value' if invalid else ('mismatch' if details else 'matched')
        missing = []
        for side, rows, key_column, field in [('left', ls, lk, 'left'), ('right', rs, rk, 'right')]:
            selected = list(dict.fromkeys([key_column] + [c[field] for c in comparisons]))
            for row in rows:
                for column in selected:
                    if not row['values'][column].strip():
                        missing.append({'side': side, 'row': row['id'], 'column': column})
        if missing and status == 'matched':
            status = 'missing_data'
        results.append({'missing_data': bool(missing), 'missing_fields': missing, 'key': key, 'status': status, 'details': details,
                        'left_rows': ls, 'right_rows': rs})
    accounted_left = sum(len(r['left_rows']) for r in results)
    accounted_right = sum(len(r['right_rows']) for r in results)
    assert accounted_left == len(left['rows']) and accounted_right == len(right['rows'])
    excluded = [r for r in results if r['missing_data']] if recipe.get('include_missing', True) is False else []
    included = [r for r in results if not r['missing_data']] if excluded else results
    return {'summary': dict(Counter(r['status'] for r in included)), 'results': included,
            'missing_groups': sum(r['missing_data'] for r in results),
            'excluded_groups': len(excluded),
            'excluded_source_rows': {'left': sum(len(r['left_rows']) for r in excluded),
                                     'right': sum(len(r['right_rows']) for r in excluded)},
            'accounting': {'left_input': len(left['rows']), 'right_input': len(right['rows']),
                           'left_accounted': accounted_left, 'right_accounted': accounted_right}}
