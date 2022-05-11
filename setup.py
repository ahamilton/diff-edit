#!/usr/bin/env python3


try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup


setup(name="diff-edit",
      version="v2022.03.16",
      description="Edit two files side by side, showing differences.",
      url="https://github.com/ahamilton/diff-edit",
      author="Andrew Hamilton",
      author_email="and_hamilton@yahoo.com",
      license="Artistic 2.0",
      packages=["diff_edit"],
      entry_points={"console_scripts": ["diff-edit=diff_edit:main"]},
      install_requires=[
          "pygments==2.10.0", "docopt==0.6.2",
          "termstr @ git+https://github.com/ahamilton/eris@v2022.05.11#subdirectory=termstr",
          "fill3 @ git+https://github.com/ahamilton/eris@v2022.05.11#subdirectory=fill3",
          "lscolors @ git+https://github.com/ahamilton/eris@v2022.05.11#subdirectory=lscolors"])
