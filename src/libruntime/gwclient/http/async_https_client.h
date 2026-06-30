/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2023-2023. All rights reserved.
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

#pragma once

#include <atomic>
#include <chrono>
#include <iostream>
#include <memory>
#include <mutex>

#include <boost/asio/ssl/error.hpp>
#include <boost/asio/ssl/stream.hpp>
#include <boost/asio/strand.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/beast/version.hpp>

#include "src/libruntime/gwclient/http/http_client.h"

namespace beast = boost::beast;
namespace http = boost::beast::http;
namespace asio = boost::asio;
namespace ssl = boost::asio::ssl;

namespace YR {
namespace Libruntime {

// CONNECT 响应可能与 TLS 首包同段到达，握手前先消费 buffer 中残留字节。
class PrefixedTcpStream {
    beast::tcp_stream s_;
    beast::flat_buffer p_;

public:
    using lowest_layer_type = asio::ip::tcp::socket;
    using executor_type = decltype(std::declval<beast::tcp_stream &>().get_executor());

    explicit PrefixedTcpStream(asio::any_io_executor ex) : s_(std::move(ex)) {}

    executor_type get_executor() noexcept { return s_.get_executor(); }
    beast::tcp_stream &stream() { return s_; }
    void setPrefix(beast::flat_buffer b) { p_ = std::move(b); }

    lowest_layer_type &lowest_layer() { return s_.socket(); }
    const lowest_layer_type &lowest_layer() const { return s_.socket(); }

    template<class B>
    std::size_t read_some(B const &b, beast::error_code &ec)
    {
        if (p_.size() > 0) {
            const std::size_t n = asio::buffer_copy(b, p_.data());
            p_.consume(n);
            ec = {};
            return n;
        }
        return s_.read_some(b, ec);
    }

    template<class B, class Token>
    auto async_read_some(B const &b, Token &&token)
    {
        if (p_.size() > 0) {
            const std::size_t n = asio::buffer_copy(b, p_.data());
            p_.consume(n);
            return asio::async_initiate<Token, void(beast::error_code, std::size_t)>(
                [n](auto h) { h(beast::error_code{}, n); }, token);
        }
        return s_.async_read_some(b, std::forward<Token>(token));
    }

    template<class B>
    std::size_t write_some(B const &b, beast::error_code &ec)
    {
        return s_.write_some(b, ec);
    }

    template<class B, class Token>
    auto async_write_some(B const &b, Token &&token)
    {
        return s_.async_write_some(b, std::forward<Token>(token));
    }

    auto &socket() { return s_.socket(); }
};

class AsyncHttpsClient : public HttpClient, public std::enable_shared_from_this<AsyncHttpsClient> {
public:
    explicit AsyncHttpsClient(const std::shared_ptr<asio::io_context> &ioc,
                              const std::shared_ptr<asio::ssl::context> &ctx,
                              std::string serverName = "");

    ~AsyncHttpsClient() override;

    ErrorInfo Init(const ConnectionParam &param) override;

    void SubmitInvokeRequest(const http::verb &method, const std::string &target,
                             const std::unordered_map<std::string, std::string> &headers, const std::string &body,
                             const std::shared_ptr<std::string> requestId,
                             const HttpCallbackFunction &receiver) override;

    void SubmitInvokeRequest(const http::verb &method, const std::string &target,
                             const std::unordered_map<std::string, std::string> &headers, const std::string &body,
                             const std::shared_ptr<std::string> requestId,
                             const HttpCallbackFunctionV2 &receiver) override;

    void SubmitInvokeRequest(const http::verb &method, const std::string &target,
                             const std::unordered_map<std::string, std::string> &headers, const std::string &body,
                             const std::shared_ptr<std::string> requestId);

    void OnRead(const std::shared_ptr<std::string> requestId, const beast::error_code &ec,
                std::size_t bytesTransferred);

    void OnWrite(const std::shared_ptr<std::string> requestId, const beast::error_code &ec,
                 std::size_t bytesTransferred);

    void Stop() override;

    void GracefulExit() noexcept override;

private:
    std::shared_ptr<asio::io_context> ioc_;
    std::shared_ptr<asio::ssl::context> ctx_;
    std::string serverName_;
    asio::ip::tcp::resolver resolver_;
    std::shared_ptr<beast::ssl_stream<PrefixedTcpStream>> stream_;
};
}  // namespace Libruntime
}  // namespace YR
