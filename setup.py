from setuptools import setup

setup(
    name='flowsa',
    version='0.0.0.1',
    packages=['flowsa'],
    package_dir={'flowsa': 'flowsa'},
    package_data={'flowsa': [
        "data/*.*", "output/*.*"]},
    include_package_data=True,
    install_requires=['pandas>=0.22'],
    url='https://github.com/USEPA/FLOWSA',
    license='CC0',
    author='Wesley Ingwersen',
    author_email='ingwersen.wesley@epa.gov',
    classifiers=[
        "Development Status :: 1 - Alpha",
        "Environment :: IDE",
        "Intended Audience :: Science/Research",
        "License :: CC0",
        "Programming Language :: Python :: 3.x",
        "Topic :: Utilities",
    ],
    description='Complies and provides a standardized list of elementary flows and flow mappings for life cycle assessment data'
)