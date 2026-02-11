"""Setup script for Stream Watcher."""

from setuptools import setup, find_packages

setup(
    name="stream-watcher",
    version="1.0.0",
    description="Cross-platform automated file sync tool for the ACB Media team",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="ACB Media",
    python_requires=">=3.13",
    packages=find_packages(),
    install_requires=[
        "watchdog>=3.0.0",
        "pystray>=0.19.0",
        "Pillow>=10.0.0",
        "keyboard>=0.13.5",
    ],
    extras_require={
        "windows": [
            "pywin32>=306",
            "accessible_output2>=0.17",
        ],
    },
    entry_points={
        "console_scripts": [
            "stream-watcher=acb_sync.__main__:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: MacOS X",
        "Environment :: Win32 (MS Windows)",
        "Intended Audience :: End Users/Desktop",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Topic :: Utilities",
    ],
)
