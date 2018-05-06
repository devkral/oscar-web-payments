#!/usr/bin/env python3
from setuptools import setup
from setuptools.command.test import test as TestCommand
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo.settings')

DJANGO_VERSIONS="django>=1.11"

PACKAGES = [
    'oscar_web_payments',
    'oscar_web_payments.payment',
    'oscar_web_payments.checkout'
    ]

REQUIREMENTS = [
    'django-oscar>=1.5,<2.0',
    'django>=1.11',
    'wtforms-django',
    'web-payments-connector>=2.4<4.0a'
]

TEST_REQUIREMENTS = [
    'pytest',
    'pytest-django'
]

VERSIONING = {
    'root': '.',
    'version_scheme': 'guess-next-dev',
    'local_scheme': 'dirty-tag',
}

EXTRAS={
    'django':  [DJANGO_VERSIONS]
}

class PyTest(TestCommand):
    user_options = [('pytest-args=', 'a', "Arguments to pass to py.test")]
    test_args = []

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.pytest_args = []

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        # import here, cause outside the eggs aren't loaded
        import pytest
        errno = pytest.main(self.pytest_args)
        sys.exit(errno)


setup(
      name='oscar-web-payments',
      license="MIT",
      author='Alexander Kaftan',
      author_email='devkral@web.de',
      description='Oscar integration for web-payments',
      use_scm_version=VERSIONING,
      setup_requires=['setuptools_scm'],
      url='http://github.com/devkral/oscar-web-payments',
      packages=PACKAGES,
      extras_require=EXTRAS,
      include_package_data=True,
      classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Development Status :: 4 - Beta',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Framework :: Django',
        'Framework :: Django :: 1.11',
        'Framework :: Django :: 2.0',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Topic :: Software Development :: Libraries :: Python Modules'],
      install_requires=REQUIREMENTS,
      cmdclass={
        'test': PyTest},
      tests_require=TEST_REQUIREMENTS,
      zip_safe=False)
