#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

with open('./requirements.txt') as f:
    INSTALL_REQUIRES = f.read().splitlines()

setup(
    name="ocp-cd-tools",
    version="0.1",
    description="CLI tools for managing and automating Red Hat software releases",
    url="https://github.com/openshift/enterprise-images",
    license="Red Hat Internal",

    package_dir={'': 'src'},
    packages=["ocp_cd_tools"],
    # scripts=['bin/oit'],
    #packages=find_packages(),
    include_package_data=True,

    entry_points = {
        'console_scripts': [
            'elliott = elliott:cli',
            'oit = oit:cli'
        ],
    },

    install_requires=INSTALL_REQUIRES,

    dependency_links=[]
)
