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
        extra_compile_args=["/std:c++20", "/EHsc", '/utf-8'] if sys.platform == 'win32' else [],
        libraries=[
            'ole32', 'uuid', 'propsys'
            # CoInitializeEx, CoCreateInstance, CoTaskMemAlloc/Free など
            # "Avrt",   # 将来、AVRT 系の API (AvSetMmThreadCharacteristicsW 等) を使うなら追加
            # "Mmdevapi", # 今は LoadLibrary で動的ロードなので必須ではない
        ],
    )
]

setup(
    name="ProcessAudioTap",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    ext_modules=ext_modules,
)