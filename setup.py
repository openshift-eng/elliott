#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

with open('./requirements.txt') as f:
    INSTALL_REQUIRES = f.read().splitlines()


def _get_version():
    from os.path import abspath, dirname, join
    filename = join(dirname(abspath(__file__)), 'elliottlib', 'VERSION')
    return open(filename).read().strip()


setup(
    name="rh-elliott",
    author="AOS ART Team",
    author_email="aos-team-art@redhat.com",
    version=_get_version(),
    description="CLI tool for managing and automating Red Hat software releases",
    long_description=open('README.md').read(),
    url="https://github.com/openshift/elliott",
    license="Red Hat Internal",
    packages=["elliottlib"],
    include_package_data=True,
    scripts=[
        'elliott'
    ],

    install_requires=INSTALL_REQUIRES,

    dependency_links=[]
)
