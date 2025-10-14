# Copyright 2015-2022 The MathWorks, Inc.
import sys
import warnings
# We start with distutils to minimize disruptions to existing workflows. 
# If distutils no longer exists, we try setuptools.
try:
    # We suppress warnings about deprecation of distutils. We will remove
    # references to distutils before it is removed from Python.
    warnings.filterwarnings('ignore', 
        message='.*distutils package is deprecated.*', 
        category=DeprecationWarning)
    from distutils.core import setup
    from distutils.command.install import install
except:
    # We suppress warnings about "setup.py install", which we continue
    # to support, though we also support pip.
    warnings.filterwarnings('ignore', 
        message='.*Use build and pip and other standards-based tools.*')
    from setuptools import setup
    from setuptools.command.install import install
    
from shutil import rmtree
from os.path import exists

class InstallAndCleanBuildArea(install):
    # Directories with these names are created during installation, but are 
    # not needed afterward (unless bdist_wheel is being executed, in which 
    # case we skip this step).
    clean_dirs = ["./build", "./dist"]

    def clean_up(self):
        for dir in self.clean_dirs:
            if exists(dir):
                rmtree(dir, ignore_errors=True) 


    def run(self):
        install.run(self)
        self.clean_up()

if __name__ == '__main__':
    setup_dict = {
        'name': 'mysum_pkg-R2022b',
        'version': '9.13',
        'description': 'A Python interface to mysum_pkg',
        'author': 'MathWorks',
        'url': 'https://www.mathworks.com/',
        'platforms': ['Linux', 'Windows', 'macOS'],
        'packages': [
            'mysum_pkg'
        ],
        'package_data': {'mysum_pkg': ['*.ctf']}
    }
    
    if not 'bdist_wheel' in sys.argv[1:]:
        setup_dict['cmdclass'] = {'install': InstallAndCleanBuildArea}
    
    setup(**setup_dict)


