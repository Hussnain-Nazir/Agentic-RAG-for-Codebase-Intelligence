from app.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def register_builtin_plugins(
        self,
        *,
        session,
        web_search_provider=None,
        settings=None,
    ) -> None:
        from app.plugins.file_reading.tool import ReadFileRangeTool, ReadFileTool
        from app.plugins.web_search.provider import SerpApiProvider
        from app.plugins.web_search.tool import SearchWebTool

        provider = web_search_provider or SerpApiProvider(settings=settings)
        self.register(ReadFileTool(session))
        self.register(ReadFileRangeTool(session))
        self.register(SearchWebTool(session, provider))
