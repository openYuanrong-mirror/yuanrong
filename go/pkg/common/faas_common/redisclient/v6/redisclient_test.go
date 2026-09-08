/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
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

package v6

import (
	"errors"
	"fmt"
	"net"
	"os"
	"sync"
	"testing"
	"time"

	"github.com/go-redis/redis"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"yuanrong.org/kernel/pkg/common/faas_common/redisclient"
)

// TestNew_InvalidMode 走 switch default 分支，立即返回 errMode，不触发任何网络建连。
func TestNew_InvalidMode(t *testing.T) {
	_, err := New(NewRedisClientParam{ServerMode: "unknown", ServerAddr: "x"})
	assert.Equal(t, errMode, err)
}

// TestClient_NilInnerReturnsNotReady 构造未初始化的 Client（内部 Cmdable 为 nil），
// 各高层方法必须立即返回 errClientNotReady，不得阻塞或 panic。
func TestClient_NilInnerReturnsNotReady(t *testing.T) {
	c := &Client{} // client 字段为 nil
	_, err := c.Get("k", 50*time.Millisecond)
	assert.Equal(t, errClientNotReady, err)
	assert.Equal(t, errClientNotReady, c.Set("k", "v", time.Second, 50*time.Millisecond))
	assert.Equal(t, errClientNotReady, c.Delete("k", 50*time.Millisecond))
	assert.Equal(t, errClientNotReady, c.Ping())
}

// TestCloseCmdable 覆盖 New 失败路径泄漏修复所用的关闭辅助函数：nil/未知实现
// no-op 不 panic，single/cluster 正常关闭。redis.NewClient/NewClusterClient 在
// 首条命令前不建连，无网络依赖。go-redis v6 二次 Close 返回 "redis: client is
// closed"（非幂等），当前调用点均只关一次，此处仅记录该语义。
func TestCloseCmdable(t *testing.T) {
	assert.NoError(t, closeCmdable(nil))
	assert.NoError(t, closeCmdable(fakeCmdable{}))

	single := redis.NewClient(&redis.Options{Addr: "127.0.0.1:0"})
	assert.NoError(t, closeCmdable(single))
	assert.EqualError(t, closeCmdable(single), "redis: client is closed")

	cluster := redis.NewClusterClient(&redis.ClusterOptions{Addrs: []string{"127.0.0.1:0"}})
	assert.NoError(t, closeCmdable(cluster))
}

type fakeCmdable struct {
	redis.Cmdable
}

// ----------------------------------------------------------------------------
// 补充用例。原则：不依赖真实 redis server，不引入 miniredis 等新依赖——
//   - 高层方法（Get/Set/Delete/Ping）的分支用可编程 fake Cmdable 驱动；
//   - 纯逻辑（doWithTimeout/configuredTimeouts/Nil 镜像）直接断言；
//   - New 的失败路径用本地 TCP 行为（连接拒绝/静默连接）确定性触发；
//   - New 的成功路径仅剩构造返回值一行，由真实 server 才能覆盖，不值得为此引依赖。

// stubCmdable 可编程 Cmdable：按预设结果响应 Get/Set/Del/Ping 并记录调用参数，
// block 模拟慢命令以触发 per-op 超时。嵌入 nil 的 redis.Cmdable 仅为满足接口，
// 本包只会调用被覆写的四个方法，不会触达 promoted 的 nil 方法。
type stubCmdable struct {
	redis.Cmdable
	getVal    string
	getErr    error
	setErr    error
	delErr    error
	pingErr   error
	block     time.Duration
	getCalls  []string
	setCalls  []setCall
	delCalls  []string
	pingCalls int
}

type setCall struct {
	key   string
	value string
	ttl   time.Duration
}

func (s *stubCmdable) Get(key string) *redis.StringCmd {
	if s.block > 0 {
		time.Sleep(s.block)
	}
	s.getCalls = append(s.getCalls, key)
	return redis.NewStringResult(s.getVal, s.getErr)
}

func (s *stubCmdable) Set(key string, value interface{}, expiration time.Duration) *redis.StatusCmd {
	if s.block > 0 {
		time.Sleep(s.block)
	}
	v, _ := value.(string)
	s.setCalls = append(s.setCalls, setCall{key: key, value: v, ttl: expiration})
	return redis.NewStatusResult("OK", s.setErr)
}

func (s *stubCmdable) Del(keys ...string) *redis.IntCmd {
	if s.block > 0 {
		time.Sleep(s.block)
	}
	s.delCalls = append(s.delCalls, keys...)
	return redis.NewIntResult(1, s.delErr)
}

func (s *stubCmdable) Ping() *redis.StatusCmd {
	s.pingCalls++
	return redis.NewStatusResult("PONG", s.pingErr)
}

// pingCmdable 仅实现 Ping，用于驱动 connectRedis 的成功/失败分支。
type pingCmdable struct {
	redis.Cmdable
	err error
}

func (p pingCmdable) Ping() *redis.StatusCmd {
	return redis.NewStatusResult("PONG", p.err)
}

// TestNilMirrorsRedisNil Nil 必须与 redis.Nil 同值，调用方 errors.Is(err, Nil) 才成立。
func TestNilMirrorsRedisNil(t *testing.T) {
	assert.Equal(t, redis.Nil, Nil)
}

// TestDoWithTimeout 覆盖 per-op 超时模拟核心分支：正常返回、错误透传、超时截断。
func TestDoWithTimeout(t *testing.T) {
	t.Run("op in time returns result", func(t *testing.T) {
		v, err := doWithTimeout(func() (string, error) { return "val", nil }, time.Second)
		assert.NoError(t, err)
		assert.Equal(t, "val", v)
	})
	t.Run("op error propagated", func(t *testing.T) {
		opErr := errors.New("op fail")
		v, err := doWithTimeout(func() (string, error) { return "", opErr }, time.Second)
		assert.Equal(t, opErr, err)
		assert.Empty(t, v)
	})
	t.Run("timeout returns errOpTimeout and zero value", func(t *testing.T) {
		v, err := doWithTimeout(func() (string, error) {
			time.Sleep(300 * time.Millisecond)
			return "late", nil
		}, 20*time.Millisecond)
		assert.Equal(t, errOpTimeout, err)
		assert.Empty(t, v)
	})
}

// TestClient_Get fake Cmdable 驱动 Get 的命中/miss(Nil)/错误/超时四条路径。
func TestClient_Get(t *testing.T) {
	t.Run("hit returns value", func(t *testing.T) {
		stub := &stubCmdable{getVal: "value"}
		c := &Client{client: stub}
		v, err := c.Get("key", time.Second)
		assert.NoError(t, err)
		assert.Equal(t, "value", v)
		assert.Equal(t, []string{"key"}, stub.getCalls)
	})
	t.Run("miss returns Nil", func(t *testing.T) {
		c := &Client{client: &stubCmdable{getErr: redis.Nil}}
		v, err := c.Get("key", time.Second)
		assert.Empty(t, v)
		assert.Equal(t, Nil, err)
	})
	t.Run("op error propagated", func(t *testing.T) {
		opErr := errors.New("get fail")
		c := &Client{client: &stubCmdable{getErr: opErr}}
		v, err := c.Get("key", time.Second)
		assert.Empty(t, v)
		assert.Equal(t, opErr, err)
	})
	t.Run("slow op cut by timeout", func(t *testing.T) {
		c := &Client{client: &stubCmdable{block: 300 * time.Millisecond}}
		v, err := c.Get("key", 20*time.Millisecond)
		assert.Empty(t, v)
		assert.Equal(t, errOpTimeout, err)
	})
}

// TestClient_Set 验证 Set 的参数透传（key/value/ttl）与错误/超时路径。
func TestClient_Set(t *testing.T) {
	t.Run("ok with args pass-through", func(t *testing.T) {
		stub := &stubCmdable{}
		c := &Client{client: stub}
		assert.NoError(t, c.Set("key", "value", 3*time.Second, time.Second))
		assert.Equal(t, []setCall{{key: "key", value: "value", ttl: 3 * time.Second}}, stub.setCalls)
	})
	t.Run("op error propagated", func(t *testing.T) {
		opErr := errors.New("set fail")
		c := &Client{client: &stubCmdable{setErr: opErr}}
		assert.Equal(t, opErr, c.Set("key", "value", time.Second, time.Second))
	})
	t.Run("slow op cut by timeout", func(t *testing.T) {
		c := &Client{client: &stubCmdable{block: 300 * time.Millisecond}}
		assert.Equal(t, errOpTimeout, c.Set("key", "value", time.Second, 20*time.Millisecond))
	})
}

// TestClient_Delete 验证 Delete 的 key 透传与错误路径。
func TestClient_Delete(t *testing.T) {
	t.Run("ok with key pass-through", func(t *testing.T) {
		stub := &stubCmdable{}
		c := &Client{client: stub}
		assert.NoError(t, c.Delete("key", time.Second))
		assert.Equal(t, []string{"key"}, stub.delCalls)
	})
	t.Run("op error propagated", func(t *testing.T) {
		opErr := errors.New("del fail")
		c := &Client{client: &stubCmdable{delErr: opErr}}
		assert.Equal(t, opErr, c.Delete("key", time.Second))
	})
}

// TestClient_Ping fake Cmdable 驱动 Ping 成功/失败。
func TestClient_Ping(t *testing.T) {
	stub := &stubCmdable{}
	c := &Client{client: stub}
	assert.NoError(t, c.Ping())
	assert.Equal(t, 1, stub.pingCalls)

	c = &Client{client: &stubCmdable{pingErr: errors.New("ping fail")}}
	assert.Error(t, c.Ping())
}

// TestConfiguredTimeouts 未配置（0/负值）返回 0 交 go-redis v6 库默认兜底；
// 显式配置时按秒换算为 time.Duration。
func TestConfiguredTimeouts(t *testing.T) {
	dial, read, write, idle := configuredTimeouts(TimeoutConf{})
	assert.Zero(t, dial)
	assert.Zero(t, read)
	assert.Zero(t, write)
	assert.Zero(t, idle)

	dial, read, write, idle = configuredTimeouts(TimeoutConf{
		DialTimeout: 5, ReadTimeout: 3, WriteTimeout: 4, IdleTimeout: 300,
	})
	assert.Equal(t, 5*time.Second, dial)
	assert.Equal(t, 3*time.Second, read)
	assert.Equal(t, 4*time.Second, write)
	assert.Equal(t, 300*time.Second, idle)

	dial, _, _, _ = configuredTimeouts(TimeoutConf{DialTimeout: -1})
	assert.Zero(t, dial)
}

// TestGetSetRedisCmd 全局 getter/setter 往返；结束后还原全局，避免污染其他用例。
func TestGetSetRedisCmd(t *testing.T) {
	c := &Client{client: &stubCmdable{}}
	SetRedisCmd(c)
	t.Cleanup(func() { SetRedisCmd(nil) })
	assert.Same(t, c, GetRedisCmd())
}

// TestPingRedis 全局 client 未初始化/内部 Cmdable 为 nil 均返回 errClientNotReady，
// 就绪时透传 Ping 结果。
func TestPingRedis(t *testing.T) {
	t.Cleanup(func() { SetRedisCmd(nil) })
	assert.Equal(t, errClientNotReady, pingRedis())
	SetRedisCmd(&Client{})
	assert.Equal(t, errClientNotReady, pingRedis())
	SetRedisCmd(&Client{client: &stubCmdable{}})
	assert.NoError(t, pingRedis())
}

// TestClient_Close_NilSafe nil receiver 与未初始化内部 client 均安全返回 nil。
func TestClient_Close_NilSafe(t *testing.T) {
	var c *Client
	assert.NoError(t, c.Close())
	assert.NoError(t, (&Client{}).Close())
}

// TestConnectRedis fake Cmdable 驱动建连探测的全部分支。
func TestConnectRedis(t *testing.T) {
	t.Run("nil finished chan returns without panic", func(t *testing.T) {
		connectRedis(pingCmdable{}, nil)
	})
	t.Run("nil cmdable reports fail", func(t *testing.T) {
		ch := make(chan int, 1)
		connectRedis(nil, ch)
		assert.Equal(t, fail, <-ch)
	})
	t.Run("ping ok reports success", func(t *testing.T) {
		ch := make(chan int, 1)
		connectRedis(pingCmdable{}, ch)
		assert.Equal(t, success, <-ch)
	})
	t.Run("ping fail reports fail", func(t *testing.T) {
		ch := make(chan int, 1)
		connectRedis(pingCmdable{err: errors.New("ping fail")}, ch)
		assert.Equal(t, fail, <-ch)
	})
}

// TestCheckRedisConnectivity nil stop 通道立即返回；两个通道均非 nil 时，关闭任一
// 通道后 checker 必须及时退出（closed chan 在 select 中立即可读，无需等 60s tick）。
func TestCheckRedisConnectivity(t *testing.T) {
	t.Run("nil stop chan returns immediately", func(t *testing.T) {
		CheckRedisConnectivity(nil, make(chan struct{}))
		CheckRedisConnectivity(make(chan struct{}), nil)
	})
	t.Run("reload stop exits checker", func(t *testing.T) {
		procCh, reloadCh := make(chan struct{}), make(chan struct{})
		done := make(chan struct{})
		go func() {
			CheckRedisConnectivity(procCh, reloadCh)
			close(done)
		}()
		close(reloadCh)
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Fatal("checker did not exit after reloadStopCh closed")
		}
	})
	t.Run("proc stop exits checker", func(t *testing.T) {
		procCh, reloadCh := make(chan struct{}), make(chan struct{})
		done := make(chan struct{})
		go func() {
			CheckRedisConnectivity(procCh, reloadCh)
			close(done)
		}()
		close(procCh)
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Fatal("checker did not exit after procStopCh closed")
		}
	})
}

// freePort 借用"监听后立即关闭"取一个当前空闲的本地端口（存在极小概率被并发抢占，
// 换取不硬编码端口的可移植性）。
func freePort(t *testing.T) int {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	port := l.Addr().(*net.TCPAddr).Port
	require.NoError(t, l.Close())
	return port
}

// silentServer 启动"接受连接但永不回包"的本地 TCP 服务：dial 立即成功、读一直
// 阻塞，用于确定性触发 New 的 startupConnectTimeout 路径（不依赖不可移植的网络
// 黑洞地址）。持有已接受的连接，避免立即 EOF 让 Ping 提前失败。
func silentServer(t *testing.T) string {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	var (
		mu    sync.Mutex
		conns []net.Conn
	)
	t.Cleanup(func() {
		_ = l.Close()
		mu.Lock()
		defer mu.Unlock()
		for _, conn := range conns {
			_ = conn.Close()
		}
	})
	go func() {
		for {
			conn, err := l.Accept()
			if err != nil {
				return
			}
			mu.Lock()
			conns = append(conns, conn)
			mu.Unlock()
		}
	}()
	return l.Addr().String()
}

// TestNew_Single_ConnectRefused 端口无人监听 → Ping 立即收到连接拒绝 →
// connectRedis 重试 3 次后上报 fail，New 返回连接失败错误。
func TestNew_Single_ConnectRefused(t *testing.T) {
	_, err := New(NewRedisClientParam{
		ServerMode: "single",
		ServerAddr: fmt.Sprintf("127.0.0.1:%d", freePort(t)),
	})
	assert.EqualError(t, err, "failed to connect redis server")
}

// TestNew_Single_DialTimeout 静默服务使 Ping 挂在读上；显式 DialTimeout=1s 使
// waitCap=1s，New 必须按上限返回超时错误（并关闭底层池，由 New 失败路径保证）。
func TestNew_Single_DialTimeout(t *testing.T) {
	_, err := New(NewRedisClientParam{
		ServerMode: "single",
		ServerAddr: silentServer(t),
		Timeout:    TimeoutConf{DialTimeout: 1},
	})
	assert.EqualError(t, err, "dialing redis server timeout")
}

// TestNew_Cluster_ConnectRefused cluster 模式连接拒绝同样失败返回；cluster 内部
// 行为（slots 拉取等）不属本包职责，仅断言报错。
func TestNew_Cluster_ConnectRefused(t *testing.T) {
	_, err := New(NewRedisClientParam{
		ServerMode: "cluster",
		ServerAddr: fmt.Sprintf("127.0.0.1:%d", freePort(t)),
	})
	assert.Error(t, err)
}

// TestNew_EnableTLS_MissingCerts 默认证书路径不存在时 BuildTLSCfg 失败，
// newSingleClient/newClusterClient 返回 nil，New 返回 "failed to new redis cmd"。
// 若默认路径恰好存在（部署机上），跳过。
func TestNew_EnableTLS_MissingCerts(t *testing.T) {
	if _, err := os.Stat(redisclient.DefaultCAFile); err == nil {
		t.Skipf("default CA file %s exists, skip", redisclient.DefaultCAFile)
	}
	_, err := New(NewRedisClientParam{
		ServerMode: "single",
		ServerAddr: "127.0.0.1:6379",
		EnableTLS:  true,
	})
	assert.EqualError(t, err, "failed to new redis cmd")

	_, err = New(NewRedisClientParam{
		ServerMode: "cluster",
		ServerAddr: "127.0.0.1:6379",
		EnableTLS:  true,
	})
	assert.EqualError(t, err, "failed to new redis cmd")
}
