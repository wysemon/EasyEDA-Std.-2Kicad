import copy

from test_symbol_layout import children, one, sexpr

from euc2k.converter import safe_name, write_conversion


def test_identical_titles_have_distinct_library_names(response, tmp_path):
    second = copy.deepcopy(response)
    second['result']['uuid'] = 'a' * 32
    first = write_conversion(response, tmp_path / 'first')
    other = write_conversion(second, tmp_path / 'second')
    assert first.name != other.name
    for data, result, folder in [(response, first, 'first'), (second, other, 'second')]:
        assert result.name == safe_name(data['result']['title']) + '_' + data['result']['uuid'][:8]
        symbol = one(sexpr(result.symbol), 'symbol')
        props = {p[1]: p[2] for p in children(symbol, 'property')}
        assert symbol[1] == result.name
        assert props['Footprint'] == f'{result.name}:{result.name}'
        assert sexpr(result.footprint)[1] == result.name
        assert (tmp_path / folder / f'{result.name}.kicad_sym').is_file()
        assert (tmp_path / folder / f'{result.name}.pretty' / f'{result.name}.kicad_mod').is_file()
