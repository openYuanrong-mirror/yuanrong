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

// Package v6 基于 go-redis v6 实现 session 存储所需的 redis 初始化/Get/Set/Delete。
//
// 为何另起 v6 而非沿用 v9 redisclient：go-redis v9 连接池突发建连时 HELLO/AUTH
// 握手与命令分发竞态，产出 WRONGPASS/NOAUTH 等瞬时鉴权错误（v9 MaxRetries 不覆盖，
// 只能靠 withAuthRetry 串匹配 + 池膨胀兜底）。v6 无此竞态，根因消除，故本包不加
// withAuthRetry/isTransientAuthErr、池规模回到 sane 默认。
//
// 与 v9 redisclient 的复用关系：纯数据/配置层与 redis 库版本无关，直接复用 v9
// 导出的部分，不重复实现——
//   - 类型别名：Config / TimeoutConf / NewRedisClientParam
//   - TLS 构建：BuildCfg
//   - 默认证书路径常量：DefaultCAFile / DefaultCertFile / DefaultKeyFile
//
// 不复用 v9 ResolveTimeouts：其 8s 默认是 v9 选型，对 v6 偏松；v6 超时仅在配置显式
// 指定时覆盖，否则用 go-redis v6 库默认（Dial 5s/Read 3s/Write=Read/Idle 5min），
// 由 configuredTimeouts 返回 0 交库 init() 兜底。
//
// v6 命令无 context.Context，无法 context.WithTimeout 做 per-op 超时；用 doWithTimeout
// （goroutine+select+NewTimer）模拟，调用方传入 timeout。被超时放弃的 goroutine 在
// 客户端 ReadTimeout（默认 8s）后写入 buffered chan 退出，不泄漏（chan 容量 1）。
package v6

import (
	"errors"
	"strings"
	"sync"
	"time"

	"github.com/go-redis/redis"

	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	"yuanrong.org/kernel/pkg/common/faas_common/redisclient"
	"yuanrong.org/kernel/pkg/common/faas_common/utils"
)

const (
	// maxRetries：v6 默认 MaxRetries=0（不重试）。设 3 在瞬时网络抖动上重试，保住
	// session 亲和（miss 会丢失粘性路由）。
	maxRetries = 3
	// 周期性健康检查间隔。
	redisReconnectionInternal = 60 * time.Second
	// startupConnectTimeout：New 等待首次 Ping 建连的上限。仅启动期一次性等待，
	// 与每命令 DialTimeout 解耦——后者未配置时由 go-redis v6 库默认（5s）兜底。
	startupConnectTimeout = 8 * time.Second

	success = 0
	fail    = 1
)

var (
	// Nil 镜像 redis.Nil，调用方 errors.Is(err, Nil) 无需 import go-redis。
	Nil = redis.Nil

	errMode           = errors.New("serverMode is not single or cluster")
	errOpTimeout      = errors.New("redis op timeout")
	errClientNotReady = errors.New("redis client not ready")
)

// 复用 v9 redisclient 的纯数据/配置类型（与 redis 版本无关），避免重复定义。
type (
	Config              = redisclient.Config
	TimeoutConf         = redisclient.TimeoutConf
	NewRedisClientParam = redisclient.NewRedisClientParam
)

var (
	mu       sync.RWMutex
	redisCmd *Client
)

// GetRedisCmd -
func GetRedisCmd() *Client {
	mu.RLock()
	c := redisCmd
	mu.RUnlock()
	return c
}

// SetRedisCmd -
func SetRedisCmd(client *Client) {
	mu.Lock()
	redisCmd = client
	mu.Unlock()
}

// Client v6 redis 客户端封装。构造后 client 字段不可变（Reload 是换全局 *Client 指针，
// 不改本结构内部字段），故读 c.client 无需加锁。只暴露 session 存储所需高层方法。
type Client struct {
	client redis.Cmdable
}

// doWithTimeout 在 goroutine 中执行 op 并用 timeout 截断。v6 命令无 context，以此
// 模拟 per-op 超时。用 NewTimer+Stop 避免 time.After 的定时器泄漏；超时后 goroutine
// 仍跑完 op（受客户端 ReadTimeout 兜底）再写入 buffered chan 退出，不泄漏。
func doWithTimeout[T any](op func() (T, error), timeout time.Duration) (T, error) {
	type res struct {
		v T
		e error
	}
	ch := make(chan res, 1)
	go func() {
		v, e := op()
		ch <- res{v, e}
	}()
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case r := <-ch:
		return r.v, r.e
	case <-timer.C:
		var zero T
		return zero, errOpTimeout
	}
}

// Get 读取一个 key。miss 返回 ("", Nil)。timeout 截断单次 op。
func (c *Client) Get(key string, timeout time.Duration) (string, error) {
	cli := c.client
	if cli == nil {
		return "", errClientNotReady
	}
	return doWithTimeout(func() (string, error) {
		return cli.Get(key).Result()
	}, timeout)
}

// Set 写入 key=value 并附加 TTL。timeout 截断单次 op。
func (c *Client) Set(key, value string, ttl, timeout time.Duration) error {
	cli := c.client
	if cli == nil {
		return errClientNotReady
	}
	_, err := doWithTimeout(func() (struct{}, error) {
		return struct{}{}, cli.Set(key, value, ttl).Err()
	}, timeout)
	return err
}

// Delete 删除一个 key。timeout 截断单次 op。
func (c *Client) Delete(key string, timeout time.Duration) error {
	cli := c.client
	if cli == nil {
		return errClientNotReady
	}
	_, err := doWithTimeout(func() (struct{}, error) {
		return struct{}{}, cli.Del(key).Err()
	}, timeout)
	return err
}

// Ping 健康检查用（无 per-op 超时，受客户端 ReadTimeout 兜底）。
func (c *Client) Ping() error {
	cli := c.client
	if cli == nil {
		return errClientNotReady
	}
	_, err := cli.Ping().Result()
	return err
}

// closeCmdable 关闭底层 redis 客户端连接池。redis.Cmdable 是接口，实际持有的是
// *redis.Client 或 *redis.ClusterClient，二者均暴露 Close()。非已知实现类型时
// no-op（不 panic）。对已关闭的池再关闭、或与仍在跑的命令并发关闭均安全（命令
// 返回 err 而非 panic）。
func closeCmdable(cli redis.Cmdable) error {
	switch c := cli.(type) {
	case *redis.Client:
		return c.Close()
	case *redis.ClusterClient:
		return c.Close()
	}
	return nil
}

// Close 释放底层 redis 连接池。供 Reload 流程在换全局 client 之前关闭旧 client，
// 避免每次配置变更泄漏一组连接池（最终耗尽 fd/端口）。
//
// 注意：调用方应在已停止旧 checker goroutine（close reloadStopCh）之后再调用本方法，
// 且要容忍仍在使用旧 client 指针的 in-flight 请求失败——sessionstore op 有 per-op
// 超时且语义 fail-open，Reload 是稀有事件，可接受。
func (c *Client) Close() error {
	if c == nil || c.client == nil {
		return nil
	}
	return closeCmdable(c.client)
}

// configuredTimeouts 返回配置的超时；未配置（0）的字段返回 0，由 go-redis v6
// 库默认兜底（Dial 5s / Read 3s / Write=Read / Idle 5min）——比强制 v9 的 8s 更紧，
// 被超时放弃的 goroutine 释放连接更快，利于连接池健康。
func configuredTimeouts(t TimeoutConf) (dial, read, write, idle time.Duration) {
	if t.DialTimeout > 0 {
		dial = time.Duration(t.DialTimeout) * time.Second
	}
	if t.ReadTimeout > 0 {
		read = time.Duration(t.ReadTimeout) * time.Second
	}
	if t.WriteTimeout > 0 {
		write = time.Duration(t.WriteTimeout) * time.Second
	}
	if t.IdleTimeout > 0 {
		idle = time.Duration(t.IdleTimeout) * time.Second
	}
	return
}

// New create a v6 redis client. addr/enableTLS 直接取自 param；password 在
// newSingleClient/newClusterClient 内深拷贝给 go-redis（保证清零 param.Password
// 不破坏重连 AUTH，见 newSingleClient 注释）；超时仅在配置显式指定时覆盖，否则用
// go-redis v6 库默认（不复用 v9 ResolveTimeouts——其 8s 默认是 v9 选型，对 v6 偏松）。
func New(param NewRedisClientParam) (*Client, error) {
	// 兜底清零 config 副本：成功路径（go-redis 持有深拷贝副本，清 param.Password 安全）、
	// 失败路径（client 被丢弃，config 副本更无保留必要）。幂等，重复清安全。
	defer utils.ClearStringMemory(param.Password)
	var redisCMD redis.Cmdable
	switch param.ServerMode {
	case "single":
		redisCMD = newSingleClient(param)
	case "cluster":
		redisCMD = newClusterClient(param)
	default:
		return nil, errMode
	}
	if redisCMD == nil {
		return nil, errors.New("failed to new redis cmd")
	}
	finished := make(chan int, 1)
	go connectRedis(redisCMD, finished)
	waitCap := startupConnectTimeout
	if dial, _, _, _ := configuredTimeouts(param.Timeout); dial > 0 {
		waitCap = dial
	}
	select {
	case i, ok := <-finished:
		if ok && i == fail {
			// Ping 失败（如鉴权错）时连接可能已建立，关闭底层池防泄漏。
			if err := closeCmdable(redisCMD); err != nil {
				log.GetLogger().Warnf("close redis client after connect failure failed, err: %s", err.Error())
			}
			return nil, errors.New("failed to connect redis server")
		}
	case <-time.After(waitCap):
		log.GetLogger().Errorf("dialing redis server error with incorrect ip address:%s.", param.ServerAddr)
		// connectRedis goroutine 可能仍在 Ping；并发关闭安全（命令返回 err 而非
		// panic），goroutine 随后向 buffered chan 发送并退出，不泄漏。
		if err := closeCmdable(redisCMD); err != nil {
			log.GetLogger().Warnf("close redis client after dial timeout failed, err: %s", err.Error())
		}
		return nil, errors.New("dialing redis server timeout")
	}
	return &Client{client: redisCMD}, nil
}

func newSingleClient(param NewRedisClientParam) redis.Cmdable {
	dial, read, write, idle := configuredTimeouts(param.Timeout)
	options := &redis.Options{
		Addr:         param.ServerAddr,
		Password:     string([]byte(param.Password)),
		DialTimeout:  dial,
		ReadTimeout:  read,
		WriteTimeout: write,
		IdleTimeout:  idle,
		MaxRetries:   maxRetries,
	}
	if param.EnableTLS {
		tlsConfig, err := redisclient.BuildTLSCfg(redisclient.DefaultCAFile, redisclient.DefaultCertFile, redisclient.DefaultKeyFile)
		if err != nil {
			utils.ClearStringMemory(options.Password)
			log.GetLogger().Errorf("failed to build single client tls config: %s", err.Error())
			return nil
		}
		options.TLSConfig = tlsConfig
	}
	return redis.NewClient(options)
}

func newClusterClient(param NewRedisClientParam) redis.Cmdable {
	dial, read, write, idle := configuredTimeouts(param.Timeout)
	options := &redis.ClusterOptions{
		Addrs:        strings.Split(param.ServerAddr, ","),
		Password:     string([]byte(param.Password)),
		DialTimeout:  dial,
		ReadTimeout:  read,
		WriteTimeout: write,
		IdleTimeout:  idle,
		MaxRetries:   maxRetries,
	}
	if param.EnableTLS {
		tlsConfig, err := redisclient.BuildTLSCfg(redisclient.DefaultCAFile, redisclient.DefaultCertFile, redisclient.DefaultKeyFile)
		if err != nil {
			utils.ClearStringMemory(options.Password)
			log.GetLogger().Errorf("failed to build redis ClusterClient tls config: %s", err.Error())
			return nil
		}
		options.TLSConfig = tlsConfig
	}
	return redis.NewClusterClient(options)
}

func connectRedis(redisCmd redis.Cmdable, finished chan<- int) {
	if finished == nil {
		return
	}
	// 防御：正常路径 New 已保证非 nil；若仍为 nil，直接上报 fail。不能落到下方
	// err.Error()——那时 err 恒为 nil，会 panic。
	if redisCmd == nil {
		log.GetLogger().Errorf("redis is not ready")
		finished <- fail
		return
	}
	var err error
	for i := 0; i < maxRetries; i++ {
		_, err = redisCmd.Ping().Result()
		if err == nil {
			finished <- success
			return
		}
	}
	log.GetLogger().Errorf("dialing redis server error: %s", err.Error())
	finished <- fail
}

// CheckRedisConnectivity 周期性 Ping 全局 Redis client 做健康监测，仅记录失败日志，
//
// 两个 stop 通道职责分离，避免 Reload 与进程退出耦合：
//   - procStopCh:   进程级生命周期，进程退出时关闭
//   - reloadStopCh: Reload 级生命周期，BuildRedisClient 每次调用 close 旧的建新的；
//     旧 goroutine 立即从 select 退出，让位给新 goroutine Ping 新 cfg 下创建的 client
func CheckRedisConnectivity(procStopCh, reloadStopCh <-chan struct{}) {
	if procStopCh == nil || reloadStopCh == nil {
		log.GetLogger().Errorf("stopCh is nil")
		return
	}
	ticker := time.NewTicker(redisReconnectionInternal)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			if err := pingRedis(); err != nil {
				log.GetLogger().Errorf("redis ping failed, err: %s", err.Error())
			}
		case <-reloadStopCh:
			log.GetLogger().Infof("redis checker exit for reload")
			return
		case <-procStopCh:
			log.GetLogger().Infof("redis checker exit for process exit")
			return
		}
	}
}

// pingRedis 取当前全局 client 做 Ping；client 未初始化或 Ping 失败均返回 err。
func pingRedis() error {
	cmd := GetRedisCmd()
	if cmd == nil {
		return errClientNotReady
	}
	return cmd.Ping()
}
