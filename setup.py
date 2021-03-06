#!/usr/bin/env python

from setuptools import setup

def check_libyaml():
    import subprocess
    if not subprocess.check_output(['brew', 'ls', '--versions', 'libyaml']):
        import sys
        sys.stderr.write('Error: {}\nError: libyaml not installed. Use `brew install libyaml` to install it\nError: {}\n'.format('*' * 80, '*' * 80))
        exit(-1)

check_libyaml()


setup(
    name='punic',
    version='0.1.13',
    url='http://github.com/schwa/punic',
    license='MIT',
    author='Jonathan Wight',
    author_email='jwight@mac.com',
    description='Clean room python implementation of a subset of Carthage functionality',
    packages=['punic'],
    install_requires=[
        'affirm',
        'blessings',
        'boto',
        'click',
        'click_didyoumean',
        'flufl.enum',
        'memoize',
        'networkx',
        'pathlib2',
        'prompt_toolkit',
        'pyyaml',
        'requests',
        'six',
        'tqdm',
        ],
    entry_points='''
        [console_scripts]
        punic=punic.punic_cli:main
        ''',
)
