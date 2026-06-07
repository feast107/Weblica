from setuptools import setup, find_packages

setup(
    name="weblica",
    version="0.1.0",
    description="Intelligent Web Application Exploration & Replaying Tool",
    author="Weblica Team",
    packages=find_packages(),
    install_requires=[
        "playwright>=1.40.0",
        "aiohttp>=3.9.0",
        "aiofiles>=23.0.0",
        "Pillow>=10.0.0",
        "fastapi>=0.100.0",
    ],
    python_requires=">=3.9",
    entry_points={
        "console_scripts": [
            "weblica=weblica.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Software Development :: Testing",
    ],
)
