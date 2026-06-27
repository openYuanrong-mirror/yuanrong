/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2023-2024. All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.yuanrong.jni;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.Channels;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.ReadableByteChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashMap;
import java.util.InvalidPropertiesFormatException;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Properties;

/**
 * The type for loading JNI library.
 *
 * @since 2024 06/14
 */
public class LoadUtil {
    private static final Logger LOGGER = LoggerFactory.getLogger(LoadUtil.class);

    private static final String DEFAULT_JNI_FOLDER = "/tmp/yr-jni";

    private static final String LIBRARY_TO_LOAD = "runtime_lib_jni";

    private static final int READ_SIZE = 8192; // 8KB

    private static final Map<String, String> SYMLINK_MAP = new HashMap<>();

    static {
        SYMLINK_MAP.put("libgrpc++.so.1.65.4", "libgrpc++.so.1.65");
        SYMLINK_MAP.put("libgrpc.so.42.0.0", "libgrpc.so.42");
        SYMLINK_MAP.put("libupb_json_lib.so.42.0.0", "libupb_json_lib.so.42");
        SYMLINK_MAP.put("libupb_textformat_lib.so.42.0.0", "libupb_textformat_lib.so.42");
        SYMLINK_MAP.put("libutf8_range_lib.so.42.0.0", "libutf8_range_lib.so.42");
        SYMLINK_MAP.put("libupb_message_lib.so.42.0.0", "libupb_message_lib.so.42");
        SYMLINK_MAP.put("libupb_base_lib.so.42.0.0", "libupb_base_lib.so.42");
        SYMLINK_MAP.put("libupb_mem_lib.so.42.0.0", "libupb_mem_lib.so.42");
        SYMLINK_MAP.put("libgpr.so.42.0.0", "libgpr.so.42");
        SYMLINK_MAP.put("libaddress_sorting.so.42.0.0", "libaddress_sorting.so.42");
        SYMLINK_MAP.put("libgflags.so.2.2.2", "libgflags.so.2.2");
    }

    // Native libraries that must be present for indirect dependencies, but are not loaded explicitly.
    private static final String[][] EXTRACT_ONLY_LIBS = {
        {"libgrpc++.so.1.65.4"},
        {"libgrpc.so.42.0.0"},
        {"libupb_json_lib.so.42.0.0"},
        {"libupb_textformat_lib.so.42.0.0"},
        {"libutf8_range_lib.so.42.0.0"},
        {"libupb_message_lib.so.42.0.0"},
        {"libupb_base_lib.so.42.0.0"},
        {"libupb_mem_lib.so.42.0.0"},
        {"libgpr.so.42.0.0"},
        {"libaddress_sorting.so.42.0.0", "libaddress_sorting.42.0.0.dylib"},
        {"libgflags.so.2.2.2"},
        {"libprotoc.so.25.5.0"},
        {"libbrpc.so"}
    };

    // Native libraries depend on each other and need to be loaded in a stable sequence.
    private static final String[][] LOADING_SEQUENCE = {
        {"libsecurec.so", "libsecurec.dylib"},
        {"libtbb.so.2", "libtbb.2.dylib"},
        {"libcrypto.so.3", "libcrypto.so.1.1", "libcrypto.dylib"},
        {"libssl.so.3", "libssl.so.1.1", "libssl.dylib"},
        {"libds-spdlog.so.1.12.0", "libds-spdlog.1.12.0.dylib"},
        {"libzmq.so.5.2.5", "libzmq.5.2.5.dylib"},
        {"libabseil_dll.so.2407.0.0"},
        {"libprotobuf.so.25.5.0"},
        {"librpc_option_protos.so"},
        {"libcommon_flags.so"},
        {"libetcdapi_proto.so"},
        {"libprotoc.so.25.5.0"},
        {"libdatasystem.so", "libdatasystem.dylib"},
        {"libspdlog.so.1.12.0", "libspdlog.1.12.0.dylib"},
        {"libyrlogs.so", "libyrlogs.dylib"},
        {"liblitebus.so.0.0.1", "liblitebus.0.0.1.dylib"},
        {"libobservability-metrics.so", "libobservability-metrics.dylib"},
        {"libobservability-metrics-sdk.so", "libobservability-metrics-sdk.dylib"},
        {"libgrpc_dynamic.so.1.65.4"},
        {"libruntime_lib_jni.so", "libruntime_lib_jni.dylib"}
    };

    /**
     * the loadLibrary
     */
    public static void loadLibrary() {
        if (loadLibraryWithJvmParam()) {
            return;
        }
        // Load so.properties from SDK jar file
        String libPath = File.separator + "native" + File.separator + getArchitecture();
        String propertiesPath = Paths.get(libPath, "so.properties").toString();
        try {
            Properties properties = loadProperties(propertiesPath);

            // Create local persistent .so file folder DEFAULT_JNI_FOLDER
            File jniDir = Paths.get(DEFAULT_JNI_FOLDER).toFile();
            if (!jniDir.exists() && !jniDir.mkdirs()) {
                throw new ExceptionInInitializerError("Failed to create folder: " + jniDir.getAbsolutePath());
            }
            extractAndSymlink(properties, libPath);
            for (String[] soFileNames : LOADING_SEQUENCE) {
                Optional<String> soFileName = findPackagedLibrary(properties, soFileNames);
                if (!soFileName.isPresent()) {
                    continue;
                }
                String libraryName = soFileName.get();
                String soFileHash = properties.getProperty(libraryName);
                String soFilePath = Paths.get(libPath, libraryName).toString();
                loadPackagedLibrary(libraryName, soFilePath, soFileHash);
            }
            if (!findPackagedLibrary(properties, LOADING_SEQUENCE[LOADING_SEQUENCE.length - 1]).isPresent()) {
                throw new InvalidPropertiesFormatException("runtime JNI library is missing from SDK jar");
            }
        } catch (IOException e) {
            throw new ExceptionInInitializerError(e);
        }
    }

    private static void extractAndSymlink(Properties properties, String libPath) throws IOException {
        for (String[] soFileNames : EXTRACT_ONLY_LIBS) {
            Optional<String> soFileName = findPackagedLibrary(properties, soFileNames);
            if (!soFileName.isPresent()) {
                continue;
            }
            String libraryName = soFileName.get();
            String soFileHash = properties.getProperty(libraryName);
            String soFilePath = Paths.get(libPath, libraryName).toString();
            extractPackagedLibrary(libraryName, soFilePath, soFileHash);
            createSymlink(libraryName);
        }
    }

    private static void extractPackagedLibrary(String libraryName, String soFilePath, String soFileHash)
            throws IOException {
        File localSoFile = Paths.get(DEFAULT_JNI_FOLDER, libraryName).toFile();
        File lockFile = Paths.get(DEFAULT_JNI_FOLDER, libraryName + ".lock").toFile();
        try (FileChannel lockChannel = FileChannel.open(lockFile.toPath(), StandardOpenOption.CREATE,
                StandardOpenOption.WRITE); FileLock ignored = lockChannel.lock()) {
            boolean isSoFileExist = localSoFile.exists();
            boolean isCheckSumMatch = isSoFileExist && checkSHA256(localSoFile, soFileHash);

            if (isSoFileExist && isCheckSumMatch && isReadableFile(localSoFile)) {
                LOGGER.debug("Cache hit for {}, skip extraction", libraryName);
                return;
            }

            if (!prepareLocalSoFile(localSoFile)) {
                copyTempSoFile(libraryName, soFilePath);
                return;
            }

            copySoFile(soFilePath, localSoFile);
            verifyExtractedSoFile(libraryName, localSoFile, soFileHash);
        }
    }

    /**
     * Verify the integrity
     *
     * @param soFileName name of the .so file, used to build the failure message
     * @param localSoFile the freshly extracted local .so file to verify
     * @param soFileHash the expected SHA-256 hex digest read from so.properties
     *
     * @throws InvalidPropertiesFormatException if the recomputed hash does not
     *     match
     * @throws IOException if an I/O error occurs while reading the file
     */
    private static void verifyExtractedSoFile(String soFileName, File localSoFile, String soFileHash)
            throws IOException {
        if (!checkSHA256(localSoFile, soFileHash)) {
            throw new InvalidPropertiesFormatException("the hash is not match for " + soFileName
                    + " after re-extraction from SDK jar: " + localSoFile.getAbsolutePath());
        }
    }

    private static void createSymlink(String soFileName) {
        String linkName = SYMLINK_MAP.get(soFileName);
        if (linkName == null) {
            return;
        }
        try {
            File linkFile = Paths.get(DEFAULT_JNI_FOLDER, linkName).toFile();
            File targetFile = Paths.get(DEFAULT_JNI_FOLDER, soFileName).toFile();
            Files.deleteIfExists(linkFile.toPath());
            Files.createSymbolicLink(linkFile.toPath(), targetFile.toPath());
        } catch (IOException e) {
            LOGGER.warn("Failed to create symlink for {}: {}", soFileName, e.getMessage());
        }
    }

    private static void loadPackagedLibrary(String libraryName, String soFilePath, String soFileHash)
            throws IOException {
        File localSoFile = Paths.get(DEFAULT_JNI_FOLDER, libraryName).toFile();
        File lockFile = Paths.get(DEFAULT_JNI_FOLDER, libraryName + ".lock").toFile();
        try (FileChannel lockChannel = FileChannel.open(lockFile.toPath(), StandardOpenOption.CREATE,
                StandardOpenOption.WRITE); FileLock ignored = lockChannel.lock()) {
            boolean isSoFileExist = localSoFile.exists();
            boolean isCheckSumMatch = isSoFileExist && checkSHA256(localSoFile, soFileHash);

            if (isSoFileExist && isCheckSumMatch && isReadableFile(localSoFile)) {
                System.load(localSoFile.getCanonicalPath());
                return;
            }

            if (!prepareLocalSoFile(localSoFile)) {
                copyAndLoadTempSoFile(libraryName, soFilePath);
                return;
            }

            if (!copyAndLoadSoFile(soFilePath, localSoFile)) {
                copyAndLoadTempSoFile(libraryName, soFilePath);
            }
        }
    }

    private static void copySoFile(String soFilePath, File localSoFile) throws IOException {
        if (!localSoFile.exists() && !localSoFile.createNewFile()) {
            throw new ExceptionInInitializerError("Failed to create file: " + localSoFile.getAbsolutePath());
        }
        try (FileChannel outChannel = FileChannel.open(localSoFile.toPath(), StandardOpenOption.WRITE,
                StandardOpenOption.TRUNCATE_EXISTING); FileLock soLock = outChannel.lock()) {
            if (soLock == null) {
                LOGGER.info("Not get lock of file: {}", localSoFile.getAbsolutePath());
                return;
            }
            copyJarSoToLocal(soFilePath, outChannel);
            if (!localSoFile.setReadOnly()) {
                LOGGER.warn("set file: {} read permission failed.", localSoFile.getAbsolutePath());
            }
        }
    }

    private static boolean isReadableFile(File file) {
        return file.isFile() && file.canRead() && file.length() > 0;
    }

    private static boolean prepareLocalSoFile(File localSoFile) throws IOException {
        if (!localSoFile.exists()) {
            return true;
        }
        if (isReadableFile(localSoFile) && localSoFile.canWrite()) {
            return true;
        }
        try {
            Files.deleteIfExists(localSoFile.toPath());
            return true;
        } catch (IOException e) {
            LOGGER.warn("failed to delete invalid local so file {}, fallback to temp copy: {}",
                    localSoFile.getAbsolutePath(), e.getMessage());
            return false;
        }
    }

    private static Optional<String> findPackagedLibrary(Properties properties, String[] candidates) {
        for (String candidate : candidates) {
            if (properties.getProperty(candidate) != null) {
                return Optional.of(candidate);
            }
        }
        return Optional.empty();
    }

    private static boolean loadLibraryWithJvmParam() {
        try {
            // If the '-Djava.library.path' parameter is set,
            // the library can be load directly.
            System.loadLibrary(LIBRARY_TO_LOAD);
            return true;
        } catch (UnsatisfiedLinkError err) {
            LOGGER.debug("Error loading native library: {}, exception msg: {}, start to load lib from sdk jar.",
                    LIBRARY_TO_LOAD, err.getMessage());
            return false;
        }
    }

    private static Properties loadProperties(String propertiesPath) throws IOException {
        try (InputStream in = LoadUtil.class.getResourceAsStream(propertiesPath)) {
            if (in == null) {
                throw new FileNotFoundException("File '" + propertiesPath + "' does not exist in SDK jar");
            }
            Properties props = new Properties();
            props.load(in);
            return props;
        }
    }

    /**
     * check file SHA256
     *
     * @param file the file
     * @param hash the hash
     * @return boolean
     */
    public static boolean checkSHA256(File file, String hash) {
        if (!file.exists()) {
            return false;
        }
        MessageDigest md;
        // Hold a shared file lock while reading so concurrent writers (another JVM
        // copying the .so from the SDK jar) cannot expose a half-written file.
        // Read directly via ByteBuffer (not Channels.newInputStream) so the lock is
        // released before the channel closes — no double-close interaction.
        try (FileChannel channel = FileChannel.open(file.toPath(), StandardOpenOption.READ);
                FileLock lock = channel.lock(0, Long.MAX_VALUE, true)) {
            md = MessageDigest.getInstance("SHA-256");
            ByteBuffer buf = ByteBuffer.allocate(READ_SIZE);
            while (channel.read(buf) != -1) {
                buf.flip();
                md.update(buf);
                buf.clear();
            }
        } catch (IOException | NoSuchAlgorithmException e) {
            throw new ExceptionInInitializerError(e);
        }

        StringBuilder strbuilder = new StringBuilder();
        for (byte oneByte : md.digest()) {
            strbuilder.append(String.format("%02x", oneByte));
        }
        return MessageDigest.isEqual(hash.getBytes(StandardCharsets.UTF_8),
                strbuilder.toString().getBytes(StandardCharsets.UTF_8));
    }

    private static void copyJarSoToLocal(String path, FileChannel outChannel) throws IOException {
        try (InputStream in = LoadUtil.class.getResourceAsStream(path)) {
            if (in == null) {
                throw new FileNotFoundException("File '" + path + "' does not exist in SDK jar");
            }
            long position = 0L;
            try (ReadableByteChannel inChannel = Channels.newChannel(in)) {
                while (true) {
                    long transferred = outChannel.transferFrom(inChannel, position, READ_SIZE);
                    if (transferred <= 0) {
                        break;
                    }
                    position += transferred;
                }
            }
            outChannel.force(true);
        }
    }

    private static boolean copyAndLoadSoFile(String soFilePath, File localSoFile) throws IOException {
        if (!localSoFile.exists()) {
            if (!localSoFile.createNewFile() && !localSoFile.exists()) {
                throw new ExceptionInInitializerError("Failed to create file: " + localSoFile.getAbsolutePath());
            }
        }
        try (FileChannel outChannel = FileChannel.open(localSoFile.toPath(), StandardOpenOption.WRITE,
                StandardOpenOption.TRUNCATE_EXISTING); FileLock soLock = outChannel.lock()) {
            if (soLock == null) {
                LOGGER.info("Not get lock of file: {}", localSoFile.getAbsolutePath());
                return false;
            }
            copyJarSoToLocal(soFilePath, outChannel);
            if (!localSoFile.setReadOnly()) {
                LOGGER.warn("set file: {} read permission failed.", localSoFile.getAbsolutePath());
            }
            System.load(localSoFile.getCanonicalPath());
            return true;
        }
    }

    private static void copyAndLoadTempSoFile(String soFileName, String soFilePath) throws IOException {
        File tempSoFile = File.createTempFile("tmp", soFileName, Paths.get(DEFAULT_JNI_FOLDER).toFile());
        tempSoFile.deleteOnExit();
        try (FileChannel outChannel = FileChannel.open(tempSoFile.toPath(), StandardOpenOption.WRITE,
                StandardOpenOption.TRUNCATE_EXISTING)) {
            copyJarSoToLocal(soFilePath, outChannel);
            if (!tempSoFile.setReadOnly()) {
                LOGGER.warn("set file: {} read permission failed.", tempSoFile.getAbsolutePath());
            }
            System.load(tempSoFile.getCanonicalPath());
        }
    }

    private static void copyTempSoFile(String soFileName, String soFilePath) throws IOException {
        File tempSoFile = File.createTempFile("tmp", soFileName, Paths.get(DEFAULT_JNI_FOLDER).toFile());
        tempSoFile.deleteOnExit();
        try (FileChannel outChannel = FileChannel.open(tempSoFile.toPath(), StandardOpenOption.WRITE,
                StandardOpenOption.TRUNCATE_EXISTING)) {
            copyJarSoToLocal(soFilePath, outChannel);
            if (!tempSoFile.setReadOnly()) {
                LOGGER.warn("set file: {} read permission failed.", tempSoFile.getAbsolutePath());
            }
        }
    }

    private static String getArchitecture() {
        String osName = System.getProperty("os.name").toLowerCase(Locale.ENGLISH);
        String osArch = System.getProperty("os.arch").toLowerCase(Locale.ENGLISH);

        if (osName.contains("nix") || osName.contains("nux")) {
            if (osArch.contains("aarch64")) {
                return "aarch64";
            }
            if (osArch.contains("86") || osArch.contains("amd") && osArch.contains("64")) {
                return "x86_64";
            }
        }
        if (osName.contains("mac") || osName.contains("darwin")) {
            if (osArch.contains("aarch64") || osArch.contains("arm64")) {
                return "arm64";
            }
            if (osArch.contains("86") || osArch.contains("amd") && osArch.contains("64")) {
                return "x86_64";
            }
        }

        throw new ExceptionInInitializerError(
                String.format("Library in jar file does not support current system: [%s %s]", osName, osArch));
    }
}
