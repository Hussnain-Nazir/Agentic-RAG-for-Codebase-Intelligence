class GitHubApiError(RuntimeError):
    """Base error for GitHub API failures."""


class GitHubInstallationRevoked(GitHubApiError):
    pass


class GitHubAccessLost(GitHubApiError):
    pass


class GitHubRepositoryDeleted(GitHubApiError):
    pass


class GitHubBranchMissing(GitHubApiError):
    pass


class GitHubRateLimited(GitHubApiError):
    pass
