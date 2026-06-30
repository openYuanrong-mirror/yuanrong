# Adapted from gRPC third_party/cython.BUILD.

py_library(
    name = "cython_lib",
    srcs = glob(
        ["Cython/**/*.py"],
        exclude = [
            "**/Tests/*.py",
            "**/Build/**",
            "**/build/**",
        ],
    ) + ["cython.py"],
    data = glob(
        [
            "Cython/**/*.pyx",
            "Cython/Utility/*.*",
            "Cython/Includes/**/*.pxd",
        ],
        exclude = [
            "**/Build/**",
            "**/build/**",
        ],
    ),
    srcs_version = "PY2AND3",
    visibility = ["//visibility:public"],
)

py_binary(
    name = "cython_binary",
    srcs = ["cython.py"],
    main = "cython.py",
    srcs_version = "PY2AND3",
    visibility = ["//visibility:public"],
    deps = ["cython_lib"],
)
