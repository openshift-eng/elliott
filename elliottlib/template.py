from __future__ import absolute_import, print_function, unicode_literals
from mako.template import Template


def render_topic(template, impact="Important"):
    t = Template(template)
    return t.render(impact=impact)


def render(template, MAJOR, MINOR):
    t = Template(template)
    return t.render(MAJOR=MAJOR, MINOR=MINOR)

def render_map(template_map, replace_vars):
    return_map = {}
    for templ_key in template_map:
        return_key = render(templ_key, **replace_vars)
        return_value = render(template_map[templ_key], **replace_vars)
        return_map[return_key] = return_value
    return return_map
