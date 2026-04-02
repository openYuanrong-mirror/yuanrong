def _impl(repository_ctx):
    os_name = repository_ctx.os.name.lower()
    use_stub = ("mac" in os_name or "darwin" in os_name) and repository_ctx.attr.stub_build_file

    repository_ctx.file("WORKSPACE", "")
    if use_stub:
        repository_ctx.symlink(repository_ctx.attr.stub_build_file, repository_ctx.path("BUILD"))
        return

    path = repository_ctx.attr.path
    if path[0] != "/":
        cur_dir = repository_ctx.path(Label("//:BUILD.bazel")).dirname
        path = repository_ctx.path(str(cur_dir) + "/" + path)
    else:
        path = repository_ctx.path(path)

    if not path.exists:
        if repository_ctx.attr.stub_build_file:
            repository_ctx.symlink(repository_ctx.attr.stub_build_file, repository_ctx.path("BUILD"))
            return
        fail("Repository path does not exist: %s" % path)

    result = repository_ctx.execute(["cp", "-fr", str(path) + "/.", "."])
    if result.return_code != 0:
        fail("Failed to copy %s: %s %s" % (path, result.stderr, result.stdout))

    repository_ctx.symlink(repository_ctx.attr.build_file, repository_ctx.path("BUILD"))

platform_local_repository = repository_rule(
    implementation = _impl,
    attrs = {
        "path": attr.string(mandatory = True),
        "build_file": attr.label(mandatory = True, allow_single_file = True),
        "stub_build_file": attr.label(allow_single_file = True),
    },
    local = True,
)
