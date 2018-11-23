from setuptools import find_packages
from setuptools import setup

setup(
    name="iqe-integration-tests",
    packages=find_packages(),
    install_requires=[
        "attrs",
        "cached_property",
        "cfme-testcases",
        "click",
        "cookiecutter",
        "diaper",
        "docker",
        "dump2polarion",
        "dynaconf",
        "fauxfactory",
        "flask",
        "hvac",
        "importscan",
        "insights-core==3.0.43",
        "ipython",
        "polarion-docstrings",
        "pre-commit",
        "prometheus-client",
        "pyopenssl",
        "pytest",
        "pytest-cov",
        "pytest-polarion-collect",
        "pytest-report-parameters",
        "python-box",
        "PyYAML",
        "requests",
        "riggerlib",
        "selenium",
        "taretto>=0.5.3",
        "wait_for",
        "webdriver_kaifuku",
        "werkzeug",
        "ocdeployer",
    ],
)
