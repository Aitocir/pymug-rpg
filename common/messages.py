import json

#
#  Public message preparers
#

def plain_text(text, dest=None):
    return (0, 0, dest, text)

def error_text(text, dest=None):
    return (0, 1, dest, text)

def plain_json(json_dict, dest=None):
    return (0, 2, dest, json_dict)

def error_json(json_dict, dest=None):
    return (0, 3, dest, json_dict)

#
#  Public message analyzers
#

def dest(m):
    return m[2]

def payload(m):
    return m[3]

def is_plain_text(m):
    return m[1] == 0

#
#  Private message network formatting
#

def _unpack(package):
    if package[0] in set([0,1]):   #  text
        content = str(package[1:], encoding='utf-8')
    if package[0] in set([0,1]):   #  JSON (dictionary)
        content = str(package[1:], encoding='utf-8')
        content = json.loads(content)
    return content

def _pack(m):
    stuff = m[3]
    dest = m[2]
    type = m[1]
    header = bytes([type])
    if type in set([0,1]):
        body = bytes(stuff, encoding='utf-8')
    elif type in set([2,3]):
        body = bytes(json.dumps(stuff), encoding='utf-8')
    if dest:
        return dest, header+body
    return header+body