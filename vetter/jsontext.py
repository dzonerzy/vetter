"""JSON in zrun's strict subset: read with rt.parse and a JSON grammar,
written as json.dumps writes it (its separators, ensure_ascii).

    v = loads(rt, '{"a": [1, true]}')
    dumps(v)    # '{"a": [1, true]}'
"""

import zgram

JSON = zgram.compile(r"""
doc            = ws value ws
@silent value  = object | array | string | number | true_ | false_ | null_
object         = '{' ws (member ws (',' ws member ws)*)? '}'
member         = string ws ':' ws value
array          = '[' ws (value ws (',' ws value ws)*)? ']'
string         = '"' (escape | plain)* '"'
@silent escape = '\\' (["\\/bfnrt] | 'u' [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])
@silent plain  = [^"\\\x00-\x1f]+
number         = '-'? ('0' | [1-9] [0-9]*) ('.' [0-9]+)? ([eE] [+-]? [0-9]+)?
true_          = 'true'
false_         = 'false'
null_          = 'null'
@silent ws     = [ \t\n\r]*
""")

HEX = "0123456789abcdef"
ESCAPES = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}
UNESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def loads(rt, text):
    """A JSON text's value (zgram.ParseError: not JSON)."""
    return json_value(rt.parse(JSON, text).children[0])


def json_value(node):
    rule = node.rule
    if rule == "object":
        out = {}
        for m in node.children:
            out[json_string(m.children[0].text)] = json_value(m.children[1])
        return out
    if rule == "array":
        return [json_value(c) for c in node.children]
    if rule == "string":
        return json_string(node.text)
    if rule == "number":
        t = node.text
        if "." in t or "e" in t or "E" in t:
            return float(t)
        return int(t)
    if rule == "true_":
        return True
    if rule == "false_":
        return False
    return None


def json_string(text):
    s = text[1:len(text) - 1]
    if "\\" not in s:
        return s
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            j = s.find("\\", i)
            if j < 0:
                j = n
            out.append(s[i:j])
            i = j
            continue
        e = s[i + 1]
        if e != "u":
            out.append(UNESCAPES[e])
            i += 2
            continue
        u = int(s[i + 2:i + 6], 16)
        i += 6
        # (a surrogate pair: one character)
        if 0xD800 <= u < 0xDC00 and s[i:i + 2] == "\\u":
            lo = int(s[i + 2:i + 6], 16)
            if 0xDC00 <= lo < 0xE000:
                u = 0x10000 + ((u - 0xD800) << 10) + (lo - 0xDC00)
                i += 6
        out.append(chr(u) if not (0xD800 <= u < 0xE000) else "�")
    return "".join(out)


def dumps(v):
    """v as json.dumps writes it (its separators, ensure_ascii)."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, str):
        return quote(v)
    if isinstance(v, dict):
        return "{" + ", ".join([quote(k) + ": " + dumps(x) for k, x in v.items()]) + "}"
    if isinstance(v, list):
        return "[" + ", ".join([dumps(x) for x in v]) + "]"
    return str(v)


def quote(s):
    out = ['"']
    for c in s:
        o = ord(c)
        if c in ESCAPES:
            out.append(ESCAPES[c])
        elif 0x20 <= o < 0x7F:
            out.append(c)
        elif o >= 0x10000:
            o -= 0x10000
            out.append(u4(0xD800 + (o >> 10)))
            out.append(u4(0xDC00 + (o & 0x3FF)))
        else:
            out.append(u4(o))
    out.append('"')
    return "".join(out)


def u4(o):
    return "\\u" + HEX[(o >> 12) & 15] + HEX[(o >> 8) & 15] + HEX[(o >> 4) & 15] + HEX[o & 15]
