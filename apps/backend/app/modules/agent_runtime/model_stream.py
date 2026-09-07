"""模型原生流的最小适配接口。

不同模型 SDK 对 ``astream`` 的具体返回类型并不一致。这里不解析供应商
chunk，只负责把“如何取得异步 chunk 流”收口；chunk 的内容、思考和 usage
解析继续由 conversation 侧的领域逻辑负责，避免 runtime 依赖 LangChain。
"""

from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from typing import Any, Protocol


class ModelStreamSource(Protocol):
    """能够产生模型 chunk 的最小来源。"""

    def __call__(self) -> AsyncIterable[Any]: ...


class ModelStreamAdapter:
    """为模型流提供统一入口，并保留调用方对异常和取消的控制权。"""

    @staticmethod
    async def collect(
        source: ModelStreamSource,
        on_chunk: Callable[[Any], Awaitable[None]],
    ) -> None:
        """消费 chunk 并按顺序交给调用方处理。

        不在此处并发处理 chunk，确保增量文本顺序稳定；模型异常和
        ``CancelledError`` 原样向上传播，由 runtime/协议层统一收敛。
        """

        async for chunk in ModelStreamAdapter.stream(source):
            await on_chunk(chunk)

    @staticmethod
    async def stream(source: ModelStreamSource) -> AsyncIterator[Any]:
        """以异步迭代方式转发 chunk，保留真正的流式 backpressure。"""

        async for chunk in source():
            yield chunk
