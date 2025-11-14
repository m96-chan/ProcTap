from setuptools import setup, Extension
from setuptools import find_packages
import os

if os.name != "nt":
    raise RuntimeError("ProcessAudioTap _native backend is Windows only.")

ext_modules = [
    Extension(
        "processaudiotap._native",
        sources=["src/processaudiotap/_native.cpp"],
        language="c++",
        extra_compile_args=["/std:c++17"],
    )
]

setup(
    name="ProcessAudioTap",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    ext_modules=ext_modules,
)