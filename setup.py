from setuptools import setup, find_packages

setup(
    name="infogen",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        # Add your dependencies here
        "requests",
        "tiktoken",
        "psycopg2-binary",
        "langchain",
        "langchain-community",
    ],
    python_requires=">=3.8",
) 