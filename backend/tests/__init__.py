"""Test package.

Present so ``from tests.conftest import FakeDatabase`` resolves, which lets
integration tests import shared fakes on a type-checked path instead of
relying on pytest's implicit injection for helper classes.
"""
