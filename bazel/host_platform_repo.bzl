def _impl(repository_ctx):
    os_name = repository_ctx.os.name.lower()
    is_macos = "mac" in os_name or "darwin" in os_name
    repository_ctx.file("WORKSPACE", "")
    repository_ctx.file("BUILD", "")
    repository_ctx.file(
        "defs.bzl",
        "IS_MACOS = %s\n" % ("True" if is_macos else "False"),
    )

host_platform_repo = repository_rule(
    implementation = _impl,
    local = True,
)
