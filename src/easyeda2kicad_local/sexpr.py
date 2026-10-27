"""Small strict reader for the generated KiCad subset (no model interpretation)."""
import json
import re

TOKEN = re.compile(r'\s*(\(|\)|"(?:\\.|[^"\\])*"|[^\s()"]+)')


def loads(text):
    stack, root, offset = [], None, 0
    while offset < len(text):
        if not text[offset:].strip():
            break
        match = TOKEN.match(text, offset)
        if not match:
            raise ValueError('invalid KiCad expression')
        token, offset = match[1], match.end()
        if token == '(':
            node = []
            if stack:
                stack[-1].append(node)
            elif root is not None:
                raise ValueError('multiple KiCad expressions')
            else:
                root = node
            stack.append(node)
        elif token == ')':
            if not stack:
                raise ValueError('unexpected closing parenthesis')
            stack.pop()
        else:
            if not stack:
                raise ValueError('text outside KiCad expression')
            stack[-1].append(json.loads(token) if token.startswith('"') else token)
    if stack or not root:
        raise ValueError('incomplete KiCad expression')
    return root


def children(node, kind):
    return [part for part in node if isinstance(part, list) and part and part[0] == kind]


def contains(node, kind):
    return node[0] == kind or any(contains(part, kind) for part in node if isinstance(part, list) and part)
