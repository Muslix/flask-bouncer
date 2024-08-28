from setuptools import setup

required_modules = ['bouncer>=0.1.12', 'Flask==3.0.3', 'blinker']

setup(name='flask-bouncer',
      version='0.3.1',
      description='Flask Simple Declarative Authentication based on Ryan Bates excellent cancan library',
      url='http://github.com/bouncer-app/flask-bouncer',
      author='Jonathan Tushman',
      author_email='jonathan@zefr.com',
      install_requires=required_modules,
      license='MIT',
      py_modules=['flask_bouncer'],
      zip_safe=False,
      platforms='any',
      tests_require=['pytest'],
      test_suite='tests',
      classifiers=[
          'Environment :: Web Environment',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: BSD License',
          'Operating System :: OS Independent',
          'Programming Language :: Python',
          'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
          'Topic :: Software Development :: Libraries :: Python Modules'
      ])
