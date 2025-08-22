from setuptools import setup, find_packages

with open("requirments.txt") as f:
    rerquirements = f.read().splitlines()

setup(
    name="AI_Travel_Agent",
    version="0.1",
    author="Rida Bayi",
    author_email="bayi.rida@gmail.com",
    packages=find_packages(),
    install_requires=rerquirements,
)