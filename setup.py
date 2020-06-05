#!/usr/bin/env python

import io
from setuptools import setup

with io.open('README.md', encoding='UTF-8') as f:
	long_description = f.read()

with io.open('VERSION', encoding='UTF-8') as f:
	VERSION = f.read()

HOMEPAGE = 'https://github.com/sm-Fifteen/asgi-server-timing-middleware'
NAME = 'asgi-server-timing-middleware'

CLASSIFIERS = [
	'Development Status :: 2 - Pre-Alpha',
	'Intended Audience :: Developers',
	'License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication',
	'Programming Language :: Python',
	'Programming Language :: Python :: 3.7',
	'Programming Language :: Python :: 3.8',
	'Programming Language :: Python :: 3 :: Only',
	'Operating System :: OS Independent',
	"Topic :: Internet :: WWW/HTTP",
	'Topic :: Internet :: WWW/HTTP :: ASGI',
	'Topic :: Internet :: WWW/HTTP :: ASGI :: Middleware',
]

setup(
	name=NAME,
	version=VERSION,
	author='sm-Fifteen',
	author_email='sm-fifteen@ihateemails.invalid',
	license='CC0 1.0 Universal',
	install_requires=['yappi>=1.2.4'],
	packages=['asgi_server_timing'],
	python_requires='>=3.7, <4',
	data_files=[
		('', ['VERSION', 'LICENSE']),
	],
	description="ASGI Server-Timing Middleware",
	long_description=long_description,
	long_description_content_type='text/markdown',
	keywords="",
	classifiers=CLASSIFIERS,
	url=HOMEPAGE,
)
