"""
setup.py for PokerFlex.

Supports:
  pip install -e .
  python -m build
  pip install .

Entry point: `pokerflex` command after install.
Primary usage: `python -m pokerflex` (A1 new brain UNAMBIGUOUS default everywhere).

Packaging for standalone: see build_exe.py (PyInstaller) + optional [tray] extra.
"""

from setuptools import setup, find_packages

# Read requirements
with open("requirements.txt", encoding="utf-8") as f:
    install_requires = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="pokerflex",
    version="1.0.0",
    description="PokerFlex A1 GTO real-time assistant (brain with explo notes + ICM)",
    long_description=open("readme.md", encoding="utf-8").read() if __import__("os").path.exists("readme.md") else "",
    long_description_content_type="text/markdown",
    author="PokerFlex (built with Grok + Claude)",
    url="https://example.com/pokerflex",  # update if you publish
    packages=find_packages(include=["pokerflex", "pokerflex.*"]),
    package_data={
        "pokerflex": [
            "equity_matrix.json",
            # runtime user files (clubgg_*.json etc) are created in CWD, not packaged
        ]
    },
    include_package_data=True,
    install_requires=install_requires,
    python_requires=">=3.9",
    entry_points={
        "console_scripts": [
            "pokerflex = pokerflex.__main__:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Games/Entertainment",
    ],
    extras_require={
        "tray": ["pystray>=0.19.4"],
        "dev": ["build", "pyinstaller"],
    },
    zip_safe=False,
)
