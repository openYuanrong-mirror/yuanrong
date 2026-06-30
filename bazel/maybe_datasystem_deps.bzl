load("//bazel:datasystem_deps.bzl", "datasystem_deps")

def maybe_datasystem_deps(enabled):
    if enabled:
        datasystem_deps()
