class FileReadingError(ValueError):
    pass


class RepositoryNotFoundError(FileReadingError):
    pass


class UnauthorizedRepositoryAccessError(FileReadingError):
    pass


class PathTraversalError(FileReadingError):
    pass


class RepositoryFileNotFoundError(FileReadingError):
    pass


class UnsupportedFileTypeError(FileReadingError):
    pass


class BinaryFileError(FileReadingError):
    pass


class FileTooLargeError(FileReadingError):
    pass


class LineRangeError(FileReadingError):
    pass


class IndexNotReadyError(FileReadingError):
    pass
