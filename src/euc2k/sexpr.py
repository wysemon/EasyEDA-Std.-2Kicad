"""Small strict reader for the generated KiCad subset (no model interpretation)."""

import json
import re

from .files import MAX_INPUT_BYTES

TOKEN = re.compile(r'\s*(\(|\)|"(?:\\.|[^"\\])*"|[^\s()"]+)')
MAX_DEPTH = 64
MAX_TOKENS = 250_000


def loads(text):
    """Read exactly one complete expression, respecting quoted and escaped text."""
    if len(text) > MAX_INPUT_BYTES:
        raise ValueError('KiCad expression exceeds supported size')
    stack, root, offset = [], None, 0
    tokens = 0
    while offset < len(text):
        match = TOKEN.match(text, offset)
        if not match:
            # Scan trailing whitespace only once, not once per token (quadratic).
            if not text[offset:].strip():
                break
            raise ValueError('invalid KiCad expression')
        tokens += 1
        if tokens > MAX_TOKENS:
            raise ValueError('KiCad expression exceeds supported token count')
        token, offset = match[1], match.end()
        if token == '(':
            if len(stack) >= MAX_DEPTH:
                raise ValueError('KiCad expression exceeds supported nesting depth')
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
    return node[0] == kind or any(
        contains(part, kind) for part in node if isinstance(part, list) and part
    )


def descendants(node, kind):
    """Walk nested units/primitives without treating quoted strings as records."""
    if node and node[0] == kind:
        yield node
    for part in node:
        if isinstance(part, list):
            yield from descendants(part, kind)
