import sys
if sys.version_info < (3, 6):
    sys.exit('Sorry, Python < 3.6 is not supported.')

from setuptools import setup, find_packages

with open('./requirements.txt') as f:
    INSTALL_REQUIRES = f.read().splitlines()


setup(
    name="rh-elliott",
    author="AOS ART Team",
    author_email="aos-team-art@redhat.com",
    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    description="CLI tool for managing and automating Red Hat software releases",
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    url="https://github.com/openshift/elliott",
    license="Apache License, Version 2.0",
    packages=find_packages(exclude=["tests", "tests.*", "functional_tests", "functional_tests.*"]),
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'elliott = elliottlib.cli.__main__:main'
        ]
    },
    install_requires=INSTALL_REQUIRES,
    test_suite='tests',
    dependency_links=[],
    python_requires='>=3.6',
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Environment :: Console",
        "Operating System :: POSIX",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS",
        "License :: OSI Approved :: Apache Software License",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "Natural Language :: English",
    ]
)
