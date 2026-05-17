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

#include <gtest/gtest.h>
#include <cstdint>
#include <string>

// Binary frame protocol constants — must match ws_transport.cpp
static const uint8_t FRAME_VERSION = 0x01;
static const uint8_t OP_CREATE = 0x01;
static const uint8_t OP_INVOKE = 0x02;
static const uint8_t STATUS_SUCCESS = 0x00;
static const uint8_t STATUS_ERROR = 0x01;

// Build a request frame: [version][op][id_len_be][id][payload]
static std::string BuildRequestFrame(uint8_t op, const std::string &id, const std::string &payload)
{
    std::string frame;
    frame.reserve(4 + id.size() + payload.size());
    frame.push_back(static_cast<char>(FRAME_VERSION));
    frame.push_back(static_cast<char>(op));
    uint16_t idLen = static_cast<uint16_t>(id.size());
    frame.push_back(static_cast<char>((idLen >> 8) & 0xFF));
    frame.push_back(static_cast<char>(idLen & 0xFF));
    frame.append(id);
    frame.append(payload);
    return frame;
}

// Build a response frame: [version][status][id_len_be][id][payload]
static std::string BuildResponseFrame(uint8_t status, const std::string &id, const std::string &payload)
{
    std::string frame;
    frame.reserve(4 + id.size() + payload.size());
    frame.push_back(static_cast<char>(FRAME_VERSION));
    frame.push_back(static_cast<char>(status));
    uint16_t idLen = static_cast<uint16_t>(id.size());
    frame.push_back(static_cast<char>((idLen >> 8) & 0xFF));
    frame.push_back(static_cast<char>(idLen & 0xFF));
    frame.append(id);
    frame.append(payload);
    return frame;
}

// Parse a response frame — mirrors ProcessMessage logic in ws_transport.cpp
struct ParsedResponse {
    uint8_t version;
    uint8_t status;
    std::string id;
    std::string payload;
    bool valid;
    // For error responses
    int errCode;
    std::string errMsg;
};

static ParsedResponse ParseResponseFrame(const std::string &message)
{
    ParsedResponse result{};
    result.valid = false;

    if (message.size() < 4) {
        return result;
    }

    auto data = reinterpret_cast<const uint8_t *>(message.data());
    result.version = data[0];
    if (result.version != FRAME_VERSION) {
        return result;
    }

    result.status = data[1];
    uint16_t idLen = (static_cast<uint16_t>(data[2]) << 8) | static_cast<uint16_t>(data[3]);

    if (message.size() < 4u + idLen) {
        return result;
    }

    result.id = std::string(message.data() + 4, idLen);
    result.payload = std::string(message.data() + 4 + idLen, message.size() - 4 - idLen);
    result.valid = true;

    if (result.status == STATUS_ERROR && result.payload.size() >= 4) {
        auto ep = reinterpret_cast<const uint8_t *>(result.payload.data());
        result.errCode = (static_cast<int>(ep[0]) << 24) | (static_cast<int>(ep[1]) << 16) |
                         (static_cast<int>(ep[2]) << 8) | static_cast<int>(ep[3]);
        if (result.payload.size() > 4) {
            result.errMsg = std::string(result.payload.data() + 4, result.payload.size() - 4);
        }
    }

    return result;
}

// Build an error payload: [4B code BE][message]
static std::string BuildErrorPayload(int code, const std::string &msg)
{
    std::string payload(4, '\0');
    payload[0] = static_cast<char>((code >> 24) & 0xFF);
    payload[1] = static_cast<char>((code >> 16) & 0xFF);
    payload[2] = static_cast<char>((code >> 8) & 0xFF);
    payload[3] = static_cast<char>(code & 0xFF);
    payload.append(msg);
    return payload;
}

// === Tests ===

class WsBinaryFrameTest : public testing::Test {};

TEST_F(WsBinaryFrameTest, BuildRequestFrameCreate)
{
    std::string id = "req-001";
    std::string payload = "raw-protobuf-bytes";
    auto frame = BuildRequestFrame(OP_CREATE, id, payload);

    ASSERT_GE(frame.size(), 4u + id.size());
    EXPECT_EQ(static_cast<uint8_t>(frame[0]), FRAME_VERSION);
    EXPECT_EQ(static_cast<uint8_t>(frame[1]), OP_CREATE);

    uint16_t idLen = (static_cast<uint8_t>(frame[2]) << 8) | static_cast<uint8_t>(frame[3]);
    EXPECT_EQ(idLen, id.size());
    EXPECT_EQ(frame.substr(4, idLen), id);
    EXPECT_EQ(frame.substr(4 + idLen), payload);
}

TEST_F(WsBinaryFrameTest, BuildRequestFrameInvoke)
{
    std::string id = "uuid-1234-5678";
    std::string payload(1024, 'X'); // 1KB payload
    auto frame = BuildRequestFrame(OP_INVOKE, id, payload);

    EXPECT_EQ(static_cast<uint8_t>(frame[1]), OP_INVOKE);
    EXPECT_EQ(frame.substr(4 + id.size()), payload);
    EXPECT_EQ(frame.size(), 4 + id.size() + payload.size());
}

TEST_F(WsBinaryFrameTest, BuildRequestFrameEmptyPayload)
{
    auto frame = BuildRequestFrame(OP_CREATE, "r1", "");
    EXPECT_EQ(frame.size(), 4u + 2u); // header + "r1"
    EXPECT_EQ(frame.substr(4, 2), "r1");
}

TEST_F(WsBinaryFrameTest, ParseResponseSuccess)
{
    std::string id = "req-001";
    std::string payload = "response-protobuf";
    auto frame = BuildResponseFrame(STATUS_SUCCESS, id, payload);

    auto resp = ParseResponseFrame(frame);
    ASSERT_TRUE(resp.valid);
    EXPECT_EQ(resp.version, FRAME_VERSION);
    EXPECT_EQ(resp.status, STATUS_SUCCESS);
    EXPECT_EQ(resp.id, id);
    EXPECT_EQ(resp.payload, payload);
}

TEST_F(WsBinaryFrameTest, ParseResponseError)
{
    std::string id = "req-002";
    int errCode = 1005;
    std::string errMsg = "operation failed";
    auto errPayload = BuildErrorPayload(errCode, errMsg);
    auto frame = BuildResponseFrame(STATUS_ERROR, id, errPayload);

    auto resp = ParseResponseFrame(frame);
    ASSERT_TRUE(resp.valid);
    EXPECT_EQ(resp.status, STATUS_ERROR);
    EXPECT_EQ(resp.id, id);
    EXPECT_EQ(resp.errCode, errCode);
    EXPECT_EQ(resp.errMsg, errMsg);
}

TEST_F(WsBinaryFrameTest, ParseResponseEmptyPayload)
{
    auto frame = BuildResponseFrame(STATUS_SUCCESS, "r", "");
    auto resp = ParseResponseFrame(frame);
    ASSERT_TRUE(resp.valid);
    EXPECT_EQ(resp.id, "r");
    EXPECT_TRUE(resp.payload.empty());
}

TEST_F(WsBinaryFrameTest, ParseResponseTooShort)
{
    std::string frame = {0x01, 0x00, 0x00}; // only 3 bytes
    auto resp = ParseResponseFrame(frame);
    EXPECT_FALSE(resp.valid);
}

TEST_F(WsBinaryFrameTest, ParseResponseWrongVersion)
{
    auto frame = BuildResponseFrame(STATUS_SUCCESS, "id", "data");
    frame[0] = 0x99; // corrupt version
    auto resp = ParseResponseFrame(frame);
    EXPECT_FALSE(resp.valid);
}

TEST_F(WsBinaryFrameTest, ParseResponseTruncatedId)
{
    std::string frame = {static_cast<char>(FRAME_VERSION), STATUS_SUCCESS, 0x00, 0x0A, 'a', 'b'};
    auto resp = ParseResponseFrame(frame);
    EXPECT_FALSE(resp.valid);
}

TEST_F(WsBinaryFrameTest, ParseResponseEmpty)
{
    auto resp = ParseResponseFrame("");
    EXPECT_FALSE(resp.valid);
}

TEST_F(WsBinaryFrameTest, RoundTrip)
{
    // Simulate C++ client building request, Go server building response
    std::string reqId = "roundtrip-test";
    std::string reqPayload = "protobuf-request-data";

    // C++ builds request
    auto reqFrame = BuildRequestFrame(OP_INVOKE, reqId, reqPayload);

    // Verify request frame structure
    ASSERT_GE(reqFrame.size(), 4u);
    EXPECT_EQ(static_cast<uint8_t>(reqFrame[0]), FRAME_VERSION);
    EXPECT_EQ(static_cast<uint8_t>(reqFrame[1]), OP_INVOKE);

    // Go would send back response
    std::string respPayload = "protobuf-response-data";
    auto respFrame = BuildResponseFrame(STATUS_SUCCESS, reqId, respPayload);

    // C++ parses response
    auto resp = ParseResponseFrame(respFrame);
    ASSERT_TRUE(resp.valid);
    EXPECT_EQ(resp.id, reqId);
    EXPECT_EQ(resp.payload, respPayload);
}

TEST_F(WsBinaryFrameTest, ErrorPayloadEncoding)
{
    auto payload = BuildErrorPayload(0x000003ED, "timeout"); // 1005

    ASSERT_GE(payload.size(), 4u);
    EXPECT_EQ(static_cast<uint8_t>(payload[0]), 0x00);
    EXPECT_EQ(static_cast<uint8_t>(payload[1]), 0x00);
    EXPECT_EQ(static_cast<uint8_t>(payload[2]), 0x03);
    EXPECT_EQ(static_cast<uint8_t>(payload[3]), 0xED);
    EXPECT_EQ(payload.substr(4), "timeout");
}

TEST_F(WsBinaryFrameTest, LargePayload)
{
    std::string id = "large-test";
    std::string payload(64 * 1024, '\xAB'); // 64KB binary payload

    auto reqFrame = BuildRequestFrame(OP_INVOKE, id, payload);
    EXPECT_EQ(reqFrame.size(), 4 + id.size() + payload.size());

    auto respFrame = BuildResponseFrame(STATUS_SUCCESS, id, payload);
    auto resp = ParseResponseFrame(respFrame);
    ASSERT_TRUE(resp.valid);
    EXPECT_EQ(resp.payload.size(), payload.size());
    EXPECT_EQ(resp.payload, payload);
}

TEST_F(WsBinaryFrameTest, IdLengthBigEndian)
{
    // ID length > 255 to verify big-endian encoding
    std::string id(300, 'A');
    auto frame = BuildRequestFrame(OP_CREATE, id, "data");

    uint16_t idLen = (static_cast<uint8_t>(frame[2]) << 8) | static_cast<uint8_t>(frame[3]);
    EXPECT_EQ(idLen, 300u);
    EXPECT_EQ(frame.substr(4, 300), id);
}
