"""服务端包入口。

契约版本与 contracts/openapi.yaml 的 x-contract-version 同步维护。
"""
from __future__ import annotations

from .common import CONTRACT_VERSION

__all__ = ["CONTRACT_VERSION"]
