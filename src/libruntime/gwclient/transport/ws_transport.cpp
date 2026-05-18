/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
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

#include "src/libruntime/gwclient/transport/ws_transport.h"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <queue>
#include <thread>
#include <unordered_map>

#include <poll.h>

#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/asio/ssl.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/beast/websocket.hpp>
#include <boost/beast/websocket/ssl.hpp>

#include "src/dto/config.h"
#include "src/libruntime/libruntime_config.h"
#include "src/utility/logger/logger.h"

namespace beast = boost::beast;
namespace websocket = beast::websocket;
namespace asio = boost::asio;
namespace ssl = asio::ssl;

namespace YR {
namespace Libruntime {

const std::string POSIX_WS_PATH = "/serverless/v1/posix/ws";
const size_t MAX_WRITE_QUEUE_SIZE = 1024;

// Binary frame protocol constants
const uint8_t FRAME_VERSION = 0x01;
const uint8_t OP_CREATE = 0x01;
const uint8_t OP_INVOKE = 0x02;
const uint8_t STATUS_SUCCESS = 0x00;

const size_t FRAME_HEADER_SIZE = 4;   // version(1) + op/status(1) + id_len_be(2)
const size_t ERROR_CODE_SIZE = 4;     // 4-byte big-endian error code in error payload
const int HTTP_STATUS_OK = 200;
const int HTTP_STATUS_BAD_REQUEST = 400;

struct WriteEntry {
    std::string requestId;
    std::string message;
    bool isPing{false};
};

class WsTransportImpl {
public:
    std::string host_;
    int port_{0};
    bool enableMTLS_{false};
    std::string certFile_;
    std::string keyFile_;
    std::string caFile_;
    std::string authToken_;
    int timeoutSec_{30};
    int pingIntervalSec_{5};

    std::shared_ptr<asio::io_context> ioc_;
    std::shared_ptr<websocket::stream<beast::ssl_stream<beast::tcp_stream>>> ws_;

    std::atomic<bool> initialized_{false};
    std::atomic<bool> connected_{false};
    std::atomic<bool> running_{false};

    std::thread readThread_;

    std::mutex writeMutex_;
    std::condition_variable writeCv_;
    std::queue<WriteEntry> writeQueue_;
    std::thread writeThread_;

    std::thread timeoutThread_;

    std::mutex callbackMutex_;
    std::unordered_map<std::string, TransportCallback> pendingCallbacks_;

    std::mutex reconnectMutex_;
    std::condition_variable reconnectCv_;

    // Serializes read/write on ws_ — SSL requires mutual exclusion.
    // ReadLoop: SSL_pending()+poll() gates entry; lock → read() → unlock.
    // WriteLoop: lock → write/ping → unlock.
    // ReadLoop only calls read() when data is known-available (SSL buffer or
    // poll), so the lock is held briefly. The 100ms poll timeout provides
    // the window for WriteLoop to acquire the mutex between reads.
    std::mutex ioMutex_;

    ErrorInfo Connect()
    {
        try {
            if (!ioc_) {
                ioc_ = std::make_shared<asio::io_context>();
            }

            YRLOG_DEBUG("WsTransport connecting to: {}:{}{}", host_, port_, POSIX_WS_PATH);

            asio::ip::tcp::resolver resolver(*ioc_);
            auto const results = resolver.resolve(host_, std::to_string(port_));

            auto sslCtx = std::make_shared<ssl::context>(ssl::context::tls_client);
            sslCtx->set_options(ssl::context::default_workarounds);
            SSL_CTX_set_min_proto_version(sslCtx->native_handle(), TLS1_2_VERSION);

            sslCtx->set_verify_mode(ssl::verify_peer);
            if (!caFile_.empty()) {
                sslCtx->load_verify_file(caFile_);
            } else {
                sslCtx->set_default_verify_paths();
            }

            if (enableMTLS_) {
                if (!certFile_.empty()) {
                    sslCtx->use_certificate_chain_file(certFile_);
                }
                if (!keyFile_.empty()) {
                    sslCtx->use_private_key_file(keyFile_, ssl::context::pem);
                }
            }

            ws_ = std::make_shared<websocket::stream<beast::ssl_stream<beast::tcp_stream>>>(*ioc_, *sslCtx);

            if (!SSL_set_tlsext_host_name(ws_->next_layer().native_handle(), host_.c_str())) {
                return ErrorInfo(ErrorCode::ERR_INNER_COMMUNICATION, ModuleCode::RUNTIME,
                                 "Failed to set SNI hostname");
            }

            // Set auth header in WebSocket handshake request
            ws_->set_option(websocket::stream_base::decorator(
                [this](websocket::request_type &req) {
                    if (!authToken_.empty()) {
                        req.set("X-Auth", authToken_);
                    }
                }));

            beast::get_lowest_layer(*ws_).connect(results);
            ws_->next_layer().handshake(ssl::stream_base::client);
            ws_->handshake(host_, POSIX_WS_PATH);
            ws_->binary(true);
            ws_->control_callback(
                [](websocket::frame_type kind, beast::string_view payload) {
                    YRLOG_DEBUG("WsTransport control frame: kind={}, payload={} bytes",
                                static_cast<int>(kind), payload.size());
                });

            connected_ = true;
            reconnectCv_.notify_all();
            YRLOG_INFO("WsTransport connected to {}:{}", host_, port_);
            return ErrorInfo();
        } catch (const std::exception &e) {
            connected_ = false;
            YRLOG_ERROR("WsTransport connection failed: {}", e.what());
            return ErrorInfo(ErrorCode::ERR_INNER_COMMUNICATION, ModuleCode::RUNTIME,
                             std::string("WebSocket connection failed: ") + e.what());
        }
    }

    void ReadLoop()
    {
        YRLOG_DEBUG("WsTransport ReadLoop started");
        while (running_) {
            if (!connected_) {
                YRLOG_DEBUG("WsTransport ReadLoop waiting for connection");
                std::unique_lock<std::mutex> lock(reconnectMutex_);
                reconnectCv_.wait(lock, [this]() { return connected_.load() || !running_.load(); });
                if (!running_) {
                    break;
                }
                YRLOG_DEBUG("WsTransport ReadLoop connection restored");
                continue;
            }

            try {
                // Check SSL internal buffer first — poll() can't see data that
                // OpenSSL already consumed from the FD and buffered internally.
                bool hasPending = SSL_pending(ws_->next_layer().native_handle()) > 0;
                if (!hasPending) {
                    int fd = beast::get_lowest_layer(*ws_).socket().native_handle();
                    struct pollfd pfd{};
                    pfd.fd = fd;
                    pfd.events = POLLIN;
                    int pollRet = ::poll(&pfd, 1, 100);  // 100ms timeout
                    if (pollRet <= 0) {
                        continue;
                    }
                }

                beast::flat_buffer buffer;
                {
                    std::lock_guard<std::mutex> lock(ioMutex_);
                    ws_->read(buffer);
                }

                std::string message = beast::buffers_to_string(buffer.data());
                YRLOG_DEBUG("WsTransport received {} bytes", message.size());

                // Skip JSON control messages (e.g. pong responses from server).
                // Binary protocol frames start with a version byte, never '{'.
                if (!message.empty() && message[0] == '{') {
                    YRLOG_DEBUG("WsTransport received pong/control message, skipping");
                    continue;
                }
                ProcessMessage(message);
            } catch (const beast::system_error &e) {
                if (e.code() == boost::asio::error::would_block ||
                    e.code() == boost::asio::error::try_again) {
                    continue;
                }
                if (e.code() == websocket::error::closed || !running_) {
                    YRLOG_DEBUG("WsTransport connection closed: {}", e.what());
                } else {
                    YRLOG_WARN("WsTransport read error: {}", e.what());
                }
                connected_ = false;
                if (running_) {
                    DrainPendingCallbacks(std::string("WebSocket disconnected: ") + e.what());
                }
            } catch (const std::exception &e) {
                if (!running_) {
                    YRLOG_DEBUG("WsTransport read stopped: {}", e.what());
                } else {
                    YRLOG_WARN("WsTransport read error: {}", e.what());
                }
                connected_ = false;
                if (running_) {
                    DrainPendingCallbacks(std::string("WebSocket disconnected: ") + e.what());
                }
            }
        }
        YRLOG_DEBUG("WsTransport ReadLoop exited");
    }

    void WriteLoop()
    {
        YRLOG_DEBUG("WsTransport WriteLoop started");
        while (running_) {
            WriteEntry entry;
            {
                std::unique_lock<std::mutex> lock(writeMutex_);
                writeCv_.wait(lock, [this]() { return !writeQueue_.empty() || !running_; });
                if (!running_) {
                    break;
                }
                entry = std::move(writeQueue_.front());
                writeQueue_.pop();
            }

            if (!connected_) {
                YRLOG_WARN("WsTransport write skipped (not connected), id: {}", entry.requestId);
                if (!entry.isPing) {
                    FireCallback(entry.requestId, ErrorInfo(ErrorCode::ERR_INNER_COMMUNICATION,
                                 ModuleCode::RUNTIME, "WebSocket not connected, id: " + entry.requestId));
                }
                continue;
            }

            try {
                std::lock_guard<std::mutex> lock(ioMutex_);
                if (entry.isPing) {
                    // Send ping as a text data message instead of a WS control frame.
                    // WS control frames (2 bytes) may not reliably flush through TLS
                    // under high concurrency, causing server-side read deadline expiry.
                    static const std::string pingMsg = R"({"type":"ping"})";
                    ws_->text(true);
                    ws_->write(asio::buffer(pingMsg));
                    YRLOG_DEBUG("WsTransport ping sent");
                } else {
                    YRLOG_DEBUG("WsTransport writing {} bytes, id: {}", entry.message.size(), entry.requestId);
                    ws_->binary(true);
                    ws_->write(asio::buffer(entry.message));
                    YRLOG_DEBUG("WsTransport write done, id: {}", entry.requestId);
                }
            } catch (const std::exception &e) {
                YRLOG_WARN("WsTransport write error: {}", e.what());
                connected_ = false;
                if (!entry.isPing) {
                    FireCallback(entry.requestId, ErrorInfo(ErrorCode::ERR_INNER_COMMUNICATION,
                                 ModuleCode::RUNTIME, std::string("WebSocket write failed: ") + e.what()));
                }
            }
        }
        YRLOG_DEBUG("WsTransport WriteLoop exited");
    }

    void FireCallback(const std::string &requestId, const ErrorInfo &err)
    {
        TransportCallback callback;
        {
            std::lock_guard<std::mutex> lock(callbackMutex_);
            auto it = pendingCallbacks_.find(requestId);
            if (it != pendingCallbacks_.end()) {
                callback = it->second;
                pendingCallbacks_.erase(it);
            }
        }
        if (callback) {
            callback("", err, 0);
        }
    }

    // Drain all pending callbacks with an error when connection is lost.
    // In-flight requests will never get a response on a new connection.
    void DrainPendingCallbacks(const std::string &reason)
    {
        std::unordered_map<std::string, TransportCallback> callbacks;
        {
            std::lock_guard<std::mutex> lock(callbackMutex_);
            callbacks.swap(pendingCallbacks_);
        }
        if (!callbacks.empty()) {
            YRLOG_WARN("WsTransport draining {} pending callbacks: {}", callbacks.size(), reason);
        }
        ErrorInfo err(ErrorCode::ERR_INNER_COMMUNICATION, ModuleCode::RUNTIME, reason);
        for (auto &[id, callback] : callbacks) {
            callback("", err, 0);
        }
    }

    void TimeoutCheckLoop()
    {
        int pingCountdown = pingIntervalSec_;
        int reconnectIntervalSec = Config::Instance().YR_WEBSOCKET_RECONNECT_INTERVAL();
        int reconnectCountdown = reconnectIntervalSec;

        while (running_) {
            std::this_thread::sleep_for(std::chrono::seconds(1));
            if (!running_) {
                break;
            }

            if (connected_) {
                // --- Heartbeat ping (enqueue to WriteLoop to avoid concurrent write) ---
                if (--pingCountdown <= 0) {
                    pingCountdown = pingIntervalSec_;
                    YRLOG_DEBUG("WsTransport enqueuing ping, interval={}s", pingIntervalSec_);
                    {
                        std::lock_guard<std::mutex> lock(writeMutex_);
                        writeQueue_.push({"", "", true});
                    }
                    writeCv_.notify_one();
                }
                reconnectCountdown = reconnectIntervalSec;  // reset while connected
            } else {
                // --- Background reconnect ---
                if (--reconnectCountdown <= 0) {
                    reconnectCountdown = reconnectIntervalSec;
                    YRLOG_INFO("WsTransport attempting background reconnect to {}:{}", host_, port_);
                    // Safe without a mutex: connected_ is false here, so
                    // ReadLoop is in its wait state and WriteLoop skips writes.
                    // No thread is accessing ws_.
                    auto err = Connect();
                    if (err.OK()) {
                        YRLOG_INFO("WsTransport background reconnect succeeded");
                        pingCountdown = pingIntervalSec_;  // reset ping timer
                    } else {
                        YRLOG_WARN("WsTransport background reconnect failed: {}", err.Msg());
                    }
                }
            }
        }
    }

    void ProcessMessage(const std::string &message)
    {
        // Binary response frame: [version][status][id_len_be][id][payload]
        if (message.size() < FRAME_HEADER_SIZE) {
            YRLOG_WARN("WsTransport received frame too short: {} bytes", message.size());
            return;
        }

        auto data = reinterpret_cast<const uint8_t *>(message.data());
        uint8_t version = data[0];
        if (version != FRAME_VERSION) {
            YRLOG_WARN("WsTransport unknown frame version: {}", version);
            return;
        }

        uint8_t status = data[1];
        uint16_t idLen = (static_cast<uint16_t>(data[2]) << 8) | static_cast<uint16_t>(data[3]);

        if (message.size() < FRAME_HEADER_SIZE + idLen) {
            YRLOG_WARN("WsTransport frame truncated: need {} bytes, got {}",
                       FRAME_HEADER_SIZE + idLen, message.size());
            return;
        }

        std::string id(message.data() + FRAME_HEADER_SIZE, idLen);
        std::string payload(message.data() + FRAME_HEADER_SIZE + idLen,
                            message.size() - FRAME_HEADER_SIZE - idLen);

        YRLOG_DEBUG("WsTransport response received, id: {}, status: {:#x}, payload: {} bytes",
                    id, status, payload.size());

        TransportCallback callback;
        {
            std::lock_guard<std::mutex> lock(callbackMutex_);
            auto it = pendingCallbacks_.find(id);
            if (it != pendingCallbacks_.end()) {
                callback = it->second;
                pendingCallbacks_.erase(it);
            }
        }

        if (!callback) {
            YRLOG_WARN("WsTransport no callback for id: {}", id);
            return;
        }

        if (status == STATUS_SUCCESS) {
            YRLOG_DEBUG("WsTransport request succeeded, id: {}", id);
            callback(payload, ErrorInfo(), HTTP_STATUS_OK);
        } else {
            // Error payload: [4B error code BE][error message]
            int errCode = -1;
            std::string errMsg = "unknown error";
            if (payload.size() >= ERROR_CODE_SIZE) {
                auto ep = reinterpret_cast<const uint8_t *>(payload.data());
                errCode = (static_cast<int>(ep[0]) << 24) | (static_cast<int>(ep[1]) << 16) |
                          (static_cast<int>(ep[2]) << 8) | static_cast<int>(ep[3]);
                if (payload.size() > ERROR_CODE_SIZE) {
                    errMsg = std::string(payload.data() + ERROR_CODE_SIZE,
                                        payload.size() - ERROR_CODE_SIZE);
                }
            }
            YRLOG_DEBUG("WsTransport request failed, id: {}, code: {}, msg: {}", id, errCode, errMsg);
            callback("", ErrorInfo(static_cast<ErrorCode>(errCode), ModuleCode::RUNTIME, errMsg),
                     HTTP_STATUS_BAD_REQUEST);
        }
    }
};

// WsTransport implementation using pImpl pattern
WsTransport::WsTransport() : impl_(std::make_unique<WsTransportImpl>()) {}

WsTransport::~WsTransport() { Stop(); }

ErrorInfo WsTransport::Init(const TransportParam &param)
{
    if (impl_->initialized_) {
        return ErrorInfo();
    }

    if (!param.enableTLS && !param.enableMTLS) {
        return ErrorInfo(ErrorCode::ERR_INNER_COMMUNICATION, ModuleCode::RUNTIME,
                         "WebSocket transport requires TLS; set enableTLS or enableMTLS in TransportParam");
    }

    impl_->host_ = param.host;
    impl_->port_ = param.port;
    impl_->enableMTLS_ = param.enableMTLS;
    impl_->certFile_ = param.certFile;
    impl_->keyFile_ = param.keyFile;
    impl_->caFile_ = param.caFile;
    impl_->authToken_ = param.authToken;
    impl_->timeoutSec_ = param.timeoutSec;
    impl_->pingIntervalSec_ = Config::Instance().YR_WEBSOCKET_RECONNECT_INTERVAL();

    auto err = impl_->Connect();
    if (!err.OK()) {
        YRLOG_WARN("WsTransport initial connection failed: {}", err.Msg());
    }

    impl_->initialized_ = true;
    impl_->running_ = true;
    impl_->readThread_ = std::thread(&WsTransportImpl::ReadLoop, impl_.get());
    impl_->writeThread_ = std::thread(&WsTransportImpl::WriteLoop, impl_.get());
    impl_->timeoutThread_ = std::thread(&WsTransportImpl::TimeoutCheckLoop, impl_.get());

    YRLOG_INFO("WsTransport initialized, host: {}:{}, mTLS: {}",
               impl_->host_, impl_->port_, impl_->enableMTLS_);
    return ErrorInfo();
}

void WsTransport::SubmitRequest(const std::string &target,
                                 const std::unordered_map<std::string, std::string> &headers,
                                 const std::string &body,
                                 const std::shared_ptr<std::string> &requestId,
                                 const TransportCallback &callback)
{
    if (!impl_->initialized_) {
        callback("", ErrorInfo(ErrorCode::ERR_INNER_SYSTEM_ERROR, ModuleCode::RUNTIME,
                               "WsTransport not initialized"), 0);
        return;
    }

    if (!IsConnected()) {
        callback("", ErrorInfo(ErrorCode::ERR_INNER_COMMUNICATION, ModuleCode::RUNTIME,
                               "WebSocket not connected, id: " + *requestId), 0);
        return;
    }

    // Map target path to binary operation code
    uint8_t opCode = OP_INVOKE;
    if (target.find("create") != std::string::npos) {
        opCode = OP_CREATE;
    }

    // Build binary frame: [version][op][id_len_be][id][raw protobuf payload]
    std::string frame;
    frame.reserve(FRAME_HEADER_SIZE + requestId->size() + body.size());
    frame.push_back(static_cast<char>(FRAME_VERSION));
    frame.push_back(static_cast<char>(opCode));
    uint16_t idLen = static_cast<uint16_t>(requestId->size());
    frame.push_back(static_cast<char>((idLen >> 8) & 0xFF));
    frame.push_back(static_cast<char>(idLen & 0xFF));
    frame.append(*requestId);
    frame.append(body);

    {
        std::lock_guard<std::mutex> lock(impl_->writeMutex_);
        if (impl_->writeQueue_.size() >= MAX_WRITE_QUEUE_SIZE) {
            callback("", ErrorInfo(ErrorCode::ERR_INNER_COMMUNICATION, ModuleCode::RUNTIME,
                                   "WebSocket write queue full, id: " + *requestId), 0);
            return;
        }
        {
            std::lock_guard<std::mutex> cbLock(impl_->callbackMutex_);
            impl_->pendingCallbacks_[*requestId] = callback;
        }
        impl_->writeQueue_.push({*requestId, std::move(frame)});
    }
    impl_->writeCv_.notify_one();

    YRLOG_DEBUG("WsTransport submitted request, id: {}, op: {:#x}, target: {}", *requestId, opCode, target);
}

bool WsTransport::IsConnected() const
{
    return impl_->connected_.load();
}

void WsTransport::Stop()
{
    YRLOG_DEBUG("WsTransport stopping, pending callbacks: {}", impl_->pendingCallbacks_.size());
    impl_->running_ = false;
    impl_->connected_ = false;
    impl_->writeCv_.notify_all();
    impl_->reconnectCv_.notify_all();

    // Shutdown socket to unblock ReadLoop's poll()/read().
    try {
        boost::system::error_code ec;
        if (impl_->ws_) {
            beast::get_lowest_layer(*impl_->ws_).socket().shutdown(
                asio::ip::tcp::socket::shutdown_both, ec);
        }
    } catch (...) {
        // Ignore socket shutdown errors; best-effort to unblock ReadLoop
    }

    // Join all I/O threads FIRST so no one touches ws_ while we close it.
    if (impl_->readThread_.joinable()) {
        impl_->readThread_.join();
    }
    if (impl_->writeThread_.joinable()) {
        impl_->writeThread_.join();
    }
    if (impl_->timeoutThread_.joinable()) {
        impl_->timeoutThread_.join();
    }

    // Close after threads are stopped — no concurrent access possible.
    if (impl_->ws_) {
        try {
            beast::error_code ec;
            impl_->ws_->close(websocket::close_code::normal, ec);
        } catch (...) {
            // Ignore WebSocket close errors; connection may already be gone
        }
    }

    {
        std::lock_guard<std::mutex> lock(impl_->callbackMutex_);
        if (!impl_->pendingCallbacks_.empty()) {
            std::string ids;
            for (auto &[id, callback] : impl_->pendingCallbacks_) {
                if (!ids.empty()) ids += ", ";
                ids += id;
                callback("", ErrorInfo(ErrorCode::ERR_INNER_COMMUNICATION, ModuleCode::RUNTIME,
                                       "WebSocket transport stopped"), 0);
            }
            YRLOG_DEBUG("WsTransport stopping with {} pending callbacks: [{}]",
                        impl_->pendingCallbacks_.size(), ids);
            impl_->pendingCallbacks_.clear();
        }
    }

    impl_->connected_ = false;
    impl_->initialized_ = false;
    YRLOG_DEBUG("WsTransport stopped");
}

std::string WsTransport::Type() const { return "WebSocket"; }

std::shared_ptr<TransportClient> CreateWsTransport()
{
    return std::make_shared<WsTransport>();
}

std::shared_ptr<TransportClient> CreateWsTransportFromConfig(const std::shared_ptr<LibruntimeConfig> &config)
{
    if (!Config::Instance().YR_ENABLE_WEBSOCKET()) {
        return nullptr;
    }

    if (config->functionSystemIpAddr.empty()) {
        YRLOG_WARN("YR_ENABLE_WEBSOCKET is true but server address is empty, skip WS init");
        return nullptr;
    }

    if (!config->enableTLS && !config->enableMTLS) {
        YRLOG_WARN("YR_ENABLE_WEBSOCKET is true but TLS is not configured; WebSocket requires TLS");
        return nullptr;
    }

    TransportParam param;
    param.host = config->functionSystemIpAddr;
    param.port = config->functionSystemPort;
    param.enableTLS = config->enableTLS;
    param.enableMTLS = config->enableMTLS;
    param.certFile = config->certificateFilePath;
    param.keyFile = config->privateKeyPath;
    param.caFile = config->verifyFilePath;
    param.authToken = config->authToken;
    param.timeoutSec = Config::Instance().YR_WEBSOCKET_TIMEOUT();

    auto ws = std::make_shared<WsTransport>();
    auto err = ws->Init(param);
    if (!err.OK()) {
        YRLOG_WARN("WebSocket transport init failed: {}, fallback to HTTP", err.Msg());
        return nullptr;
    }
    YRLOG_INFO("WebSocket transport initialized: {}:{}, mTLS: {}", param.host, param.port, param.enableMTLS);
    return ws;
}

}  // namespace Libruntime
}  // namespace YR
