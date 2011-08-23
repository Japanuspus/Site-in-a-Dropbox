from __future__ import absolute_import

from . import markdown

formatters = {
    'markdown': markdown,
    }

def get_formatter_by_name(name):
    """
    Returns an initialized formatter object by name.
    Returns None for unknown formatter
    """
    if not name:
        return
    name=name.lower()
    formatter_module = formatters.get(name,None)
    if not formatter_module:
        return
    formatter=formatter_module.get_formatter()
    formatter.name = name
    return formatter
