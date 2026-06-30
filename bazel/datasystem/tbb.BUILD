load("@rules_foreign_cc//foreign_cc:defs.bzl", "make")

filegroup(
    name = "all_srcs",
    srcs = glob(["**"]),
)

# TBB 2020.3: build shared libs first (compiles all .o files), then repackage
# the object files into static archives so they can be embedded at link time.
make(
    name = "tbb",
    lib_source = ":all_srcs",
    env = {
        "CXXFLAGS": "-fPIC -O2 -DNDEBUG",
    },
    out_static_libs = [
        "libtbb_static.a",
        "libtbbmalloc_static.a",
    ],
    out_include_dir = "include",
    targets = [
        "tbb",
        "tbbmalloc",
    ],
    postfix_script = """
        # Find the build directory - need to look in the actual source tree, not BUILD_TMPDIR
        TBB_BUILD_DIR=$(ls -d "$EXT_BUILD_ROOT"/external/ds_tbb/build/*_release 2>/dev/null | head -1)
        if [ -z "$TBB_BUILD_DIR" ]; then
            echo "ERROR: TBB build directory not found"
            exit 1
        fi
        mkdir -p "$INSTALLDIR/lib"
        # Exclude tbbmalloc proxy.o from libtbb_static.a. That object overrides
        # global operator new/delete and breaks allocator pairing when embedded
        # into libyr-api.so as a static dependency.
        TBB_OBJS=$(find "$TBB_BUILD_DIR" -maxdepth 1 -name '*.o' ! -name 'proxy.o' | sort)
        ar rcs "$INSTALLDIR/lib/libtbb_static.a" $TBB_OBJS
        # Exclude tbbmalloc-specific objects (they have their own .o files)
        MALLOC_OBJS=$(ls "$TBB_BUILD_DIR"/backend.o \
                         "$TBB_BUILD_DIR"/large_objects.o \
                         "$TBB_BUILD_DIR"/backref.o \
                         "$TBB_BUILD_DIR"/tbbmalloc.o \
                         "$TBB_BUILD_DIR"/itt_notify_malloc.o \
                         "$TBB_BUILD_DIR"/frontend.o 2>/dev/null)
        if [ -n "$MALLOC_OBJS" ]; then
            ar rcs "$INSTALLDIR/lib/libtbbmalloc_static.a" $MALLOC_OBJS
        fi
        mkdir -p "$INSTALLDIR/include"
        cp -rL "$EXT_BUILD_ROOT"/external/ds_tbb/include/tbb "$INSTALLDIR/include/"
    """,
    visibility = ["//visibility:public"],
)
