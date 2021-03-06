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
    'wtforms-django-alex',
    'web-payments-connector>=2.4<4.0a'
]

TEST_REQUIREMENTS = [
    'pytest',
    'pytest-django',
    'WebTest>=2.0,<2.1',
    'coverage>=4.5,<4.6',
    'django-webtest==1.9.2',
    'tox>=3.0,<3.1',
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
        import django
        from django.test.utils import get_runner
        import demo.settings
        #settings.configure(default_settings=demo.settings)
        django.setup()
        from django.conf import settings
        # import here, cause outside the eggs aren't loaded
        TestRunner = get_runner(settings)
        test_runner = TestRunner(verbosity=1, interactive=True)
        failures = test_runner.run_tests(test_labels=[])
        sys.exit(failures)


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
