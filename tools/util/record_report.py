#!/usr/bin/env python

from __future__ import print_function
import sys
import os
from colorprint import print


# yup, super lazy
def p(msg, **kwargs):
    print(msg, **kwargs)


def source_alias(d):
    p('SOURCE ALIASES')
    p('==============')

    for a in d:
        p('{alias}#{branch}'.format(**a), color='green')
        p('  {path}'.format(**a))


def distgit_commit(d):
    pass


def dockerfile_notify(d):
    pass


def build(d):
    p('IMAGE BUILD / PUSH')
    p('==================')

    for b in d:
        color = 'green' if (b['status'] == '0') else 'red'
        p('{distgit} - {version}-{release}'.format(**b), color=color)
        p('  Task URL: {task_url}\n  Message: {message}'.format(**b))


def push(d):
    pass


HANDLERS = {
    'source_alias': source_alias,
    # 'distgit_commit': distgit_commit,  # not needed in report
    # 'dockerfile_notify': dockerfile_notify,  # not needed in report
    'build': build,
    'push': push
}


def get_dict(lines):
    result = {}
    for l in lines:
        l = l.strip().strip('|')
        f = l.split('|')
        if f[0] not in result:
            result[f[0]] = []
        sub_dict = {}
        for sub in f[1:]:
            sub_split = sub.split('=')
            sub_dict[sub_split[0]] = '='.join(sub_split[1:])
            # some values may have = in them, above rejoins them
        result[f[0]].append(sub_dict)

    return result


if __name__ == '__main__':
    record = os.path.abspath(sys.argv[1])
    p('Parsing {}'.format(record))
    with open(record, 'r') as rec:
        data = get_dict(rec.readlines())

    for k, v in data.iteritems():
        if k in HANDLERS:
            p('\n')
            HANDLERS[k](v)
