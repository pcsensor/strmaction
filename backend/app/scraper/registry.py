"""元数据 Provider 插件化注册中心。

支持开放扩展（Open-Closed Principle）：
新增 Provider 时只需实现 MetadataProvider 协议并使用 @register_provider("name") 注册，
无需修改 ScrapeService 核心调度逻辑。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .base import MetadataProvider

if TYPE_CHECKING:
    from ..config_store import SettingsService

ProviderFactory = Callable[["SettingsService"], MetadataProvider]

_REGISTRY: dict[str, ProviderFactory] = {}


def register_provider(name: str):
    """注册元数据 Provider 工厂或类。"""

    def decorator(factory: ProviderFactory | type[MetadataProvider]):
        _REGISTRY[name.lower().strip()] = factory
        return factory

    return decorator


def get_registered_providers() -> list[str]:
    """返回所有已注册的 Provider 名称列表。"""
    return list(_REGISTRY.keys())


class ProviderRegistry:
    def __init__(self, settings: SettingsService):
        self.settings = settings
        self._providers: dict[str, MetadataProvider] = {}

    def get(self, name: str) -> MetadataProvider | None:
        key = name.lower().strip()
        if key in self._providers:
            return self._providers[key]
        factory = _REGISTRY.get(key)
        if factory is None:
            return None
        provider = factory(self.settings)
        if provider is not None:
            self._providers[key] = provider
        return provider

    async def close(self) -> None:
        for provider in self._providers.values():
            close = getattr(provider, "close", None)
            if close:
                try:
                    await close()
                except Exception:
                    pass
        self._providers.clear()
