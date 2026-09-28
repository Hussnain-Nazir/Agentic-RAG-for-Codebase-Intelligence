class ToolError(RuntimeError):
    pass


class RepositoryNotFoundError(ToolError):
    pass


class UnauthorizedRepositoryAccessError(ToolError):
    pass


class IndexNotReadyError(ToolError):
    pass


class PathTraversalError(ToolError):
    pass


class RepositoryFileNotFoundError(ToolError):
    pass


class UnsupportedFileTypeError(ToolError):
    pass


class BinaryFileError(ToolError):
    pass


class FileTooLargeError(ToolError):
    pass


class LineRangeError(ToolError):
    pass


class ToolValidationError(ToolError):
    pass


class WebSearchTimeoutError(ToolError):
    pass


class WebSearchProviderError(ToolError):
    pass
