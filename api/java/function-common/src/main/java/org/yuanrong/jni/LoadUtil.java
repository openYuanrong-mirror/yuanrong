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
import java.nio.channels.Channels;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.InvalidPropertiesFormatException;
import java.util.Locale;
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

    // Native libraries depend on each other and need to be loaded in a stable sequence.
    private static final String[][] LOADING_SEQUENCE = {
        {"libsecurec.so", "libsecurec.dylib"},
        {"libtbb.so.2", "libtbb.2.dylib"},
        {"libcrypto.so.1.1", "libcrypto.dylib"},
        {"libssl.so.1.1", "libssl.dylib"},
        {"libds-spdlog.so.1.12.0", "libds-spdlog.1.12.0.dylib"},
        {"libzmq.so.5.2.5", "libzmq.5.2.5.dylib"},
        {"libaddress_sorting.so.42.0.0", "libaddress_sorting.42.0.0.dylib"},
        {"libdatasystem.so", "libdatasystem.dylib"},
        {"libspdlog.so.1.12.0", "libspdlog.1.12.0.dylib"},
        {"libyrlogs.so", "libyrlogs.dylib"},
        {"liblitebus.so.0.0.1", "liblitebus.0.0.1.dylib"},
        {"libobservability-metrics.so", "libobservability-metrics.dylib"},
        {"libobservability-metrics-sdk.so", "libobservability-metrics-sdk.dylib"},
        {"libgrpc_dynamic.so.1.65.4"},
        {"libruntime_lib_jni.so", "libruntime_lib_jni.dylib"},
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
            for (String[] soFileNames : LOADING_SEQUENCE) {
                String soFileName = findPackagedLibrary(properties, soFileNames);
                if (soFileName == null) {
                    continue;
                }
                String soFileHash = properties.getProperty(soFileName);
                String soFilePath = Paths.get(libPath, soFileName).toString();
                File localSoFile = Paths.get(DEFAULT_JNI_FOLDER, soFileName).toFile();
                boolean isSoFileExist = localSoFile.exists();
                boolean isCheckSumMatch = checkSHA256(localSoFile, soFileHash);

                if (isSoFileExist && isCheckSumMatch) {
                    System.load(localSoFile.getCanonicalPath());
                    continue;
                }

                if (!copyAndLoadSoFile(soFilePath, localSoFile)) {
                    copyAndLoadTempSoFile(soFileName, soFilePath);
                }
            }
            if (findPackagedLibrary(properties, LOADING_SEQUENCE[LOADING_SEQUENCE.length - 1]) == null) {
                throw new InvalidPropertiesFormatException("runtime JNI library is missing from SDK jar");
            }
        } catch (IOException e) {
            throw new ExceptionInInitializerError(e);
        }
    }

    private static String findPackagedLibrary(Properties properties, String[] candidates) {
        for (String candidate : candidates) {
            if (properties.getProperty(candidate) != null) {
                return candidate;
            }
        }
        return null;
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
        try (InputStream in = Files.newInputStream(file.toPath())) {
            md = MessageDigest.getInstance("SHA-256");
            byte[] buf = new byte[READ_SIZE];
            int len = in.read(buf);
            while (len > 0) {
                md.update(buf, 0, len);
                len = in.read(buf);
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
            outChannel.transferFrom(Channels.newChannel(in), 0, Long.MAX_VALUE);
        }
    }

    private static boolean copyAndLoadSoFile(String soFilePath, File localSoFile) throws IOException {
        if (!localSoFile.exists()) {
            if (!localSoFile.createNewFile() && !localSoFile.exists()) {
                throw new ExceptionInInitializerError("Failed to create file: " + localSoFile.getAbsolutePath());
            }
        }
        try (FileChannel outChannel = FileChannel.open(localSoFile.toPath(), StandardOpenOption.WRITE,
                StandardOpenOption.APPEND); FileLock soLock = outChannel.lock()) {
            if (soLock == null) {
                LOGGER.info("Not get lock of file: {}", localSoFile.getAbsolutePath());
                return false;
            }
            if (outChannel.size() == 0) {
                copyJarSoToLocal(soFilePath, outChannel);
                if (!localSoFile.setReadOnly()) {
                    LOGGER.warn("set file: {} read permission failed.", localSoFile.getAbsolutePath());
                }
                System.load(localSoFile.getCanonicalPath());
                return true;
            }
            return false;
        }
    }

    private static void copyAndLoadTempSoFile(String soFileName, String soFilePath) throws IOException {
        File tempSoFile = File.createTempFile("tmp", soFileName, Paths.get(DEFAULT_JNI_FOLDER).toFile());
        tempSoFile.deleteOnExit();
        try (FileChannel outChannel = FileChannel.open(tempSoFile.toPath(), StandardOpenOption.WRITE,
                StandardOpenOption.APPEND)) {
            copyJarSoToLocal(soFilePath, outChannel);
            if (!tempSoFile.setReadOnly()) {
                LOGGER.warn("set file: {} read permission failed.", tempSoFile.getAbsolutePath());
            }
            System.load(tempSoFile.getCanonicalPath());
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
