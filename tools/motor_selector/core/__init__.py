# -*- coding: utf-8 -*-
"""电机选型程序核心计算包。"""
from .entities import LoadCase, Motor, Gearbox, Requirement, CheckItem, Evaluation  # noqa: F401

__all__ = ["LoadCase", "Motor", "Gearbox", "Requirement", "CheckItem", "Evaluation"]
__version__ = "1.0.0"
