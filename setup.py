import os

from setuptools import setup

readme = open(os.path.join(os.path.dirname(__file__), 'README.md'), 'r').read()

setup(
    name='virtualenv-tools3',
    author='Fireteam Ltd.; Yelp, Inc.',
    author_email='support@fireteam.net; opensource@yelp.com',
    version='2.0.0',
    url='http://github.com/Yelp/virtualenv-tools',
    py_modules=['virtualenv_tools'],
    description='A set of tools for virtualenv',
    long_description=readme,
    entry_points={
        'console_scripts': [
            'virtualenv-tools = virtualenv_tools:main'
        ]
    },
    zip_safe=False,
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ]
)
