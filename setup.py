# setup.py （or setup_native.py でもOK）
from setuptools import setup, Extension
from pathlib import Path

here = Path(__file__).parent

ext = Extension(
    "processaudiotap._native",
    sources=[str(here / "src" / "processaudiotap" / "_native.cpp")],
    language="c++",
    extra_compile_args=["/std:c++20"],
    # Windows専用なので、必要ならライブラリや定義を追加
    # libraries=["Ole32", "Mmdevapi", "Avrt"],
)

setup(
    ext_modules=[ext],
)