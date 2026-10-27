"""Source attribution, descriptions and verbatim license preservation."""
def owner(component):
    o = component.get('owner') or {}
    return o.get('nickname') or o.get('username') or 'unknown'



def render_credits(result, data, fp, package, name):
    source = f'https://easyeda.com/component/{result["uuid"]}'
    heads = [data['head'], fp['head']]
    official = any((h.get('c_para') or {}).get('Contributor') == 'LCSC' or
                   any('official' in str(v).lower() for k, v in h.items() if 'license' in k.lower()) for h in heads)
    note = ('JLCEDA/EasyEDA Official Library - https://lceda.cn/ - https://easyeda.com' if official else
            f'Contributed by {owner(result)}, {owner(package)}; rights belong to the author(s); check before redistributing')
    credits = (f'Source: {source}\nTitle: {result.get("title", name)}\nSymbol author: {owner(result)}\n'
               f'Footprint author: {owner(package)}\nupdateTime: {result.get("updateTime", "unknown")}\n'
               f'Footprint updateTime: {package.get("updateTime", "unknown")}\nLicense note: {note}\n')
    credits += f'Description (from source):\n{result.get("description") or ""}\n'
    for label, head in zip(('symbol', 'footprint'), heads):
        if isinstance(head.get('license'), str):
            credits += f'\nLicense (from source) [{label}]:\n{head["license"]}\n'
    return credits
