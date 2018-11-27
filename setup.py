#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

with open('./requirements.txt') as f:
    INSTALL_REQUIRES = f.read().splitlines()

setup(
    name="elliott",
    author="AOS ART Team",
    author_email="aos-team-art@redhat.com",
    version="0.1",
    description="CLI tool for managing and automating Red Hat software releases",
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