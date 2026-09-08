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

// Package session 提供按 session key 读写单条绑定记录的外部存储抽象。
//
// 设计目标见 faasscheduler Session 可靠性优化设计：删除函数维度整包备份与全量恢复，
// 改为请求路径懒恢复。本地 sessionMap 命中时不访问外部存储；本地 miss 时按 session
// cache key 查询外部记录，命中则懒恢复绑定关系。
//
// # 灰度（rollout）语义
//
// physicalKey 不含 SchedulerID，灰度期新老 scheduler 对同一 session 的请求会写入同一
// 物理 key、互相覆盖——这是 by design，与旧方案"按 SchedulerID 分桶 + 全量 merge"不同。
// 设计前提：路由层保证同一 session 同一时刻只归一个 scheduler 持有者；新的请求路径
// 写入会覆盖旧持有者的记录，体现"以最新 owner 为准"。崩溃后请求被路由到新 scheduler
// 时，新 scheduler 懒恢复读到的就是最新 owner 写的 record，正是正确语义。
//
// 若未来出现"灰度期同 session 同时被两个 scheduler 持有"的场景（金丝雀长期共存且
// 路由层不保证 session 粘性），需要在此处补 SchedulerID 维度的 key 分桶——目前无此场景。
package session

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"time"

	"yuanrong.org/kernel/runtime/libruntime/api"

	"yuanrong.org/kernel/pkg/common/faas_common/datasystemclient"
	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	v6 "yuanrong.org/kernel/pkg/common/faas_common/redisclient/v6"
	"yuanrong.org/kernel/pkg/common/uuid"
)

// Backend 枚举值。
//
// 生产环境只允许 Redis / DataSystem 两种（由 config 加载期强制校验）。
// BackendNoop 不对用户暴露：仅用作 MakeStore 在 New() 失败时的 fail-open
// 兜底 sentinel，使调度主流程在初始化异常时仍能继续（写入丢弃、读取 miss）。
const (
	BackendNoop       = "noop" // fail-open 兜底 sentinel，仅由 NoopStore 使用
	BackendDataSystem = "datasystem"
	BackendRedis      = "redis"

	// defaultRecoveryWindowSeconds 是外部存储 key 的默认物理 TTL（24h），Redis 与 DataSystem
	// 后端共用——保证两后端崩溃恢复窗口一致。业务 session TTL 不参与外部 key 过期（解耦，
	// 见设计文档）；正常运行时由 scheduler 内存 timer 主动 DEL 外部 key。
	defaultRecoveryWindowSeconds = 86400
	redisOpTimeout               = 500 * time.Millisecond

	hashMaxLength = 16
)

// errStoreDisabled 表示 backend 未配置或 Redis client 未初始化，store 操作 fail-open 时返回，不阻断调度主流程。
var errStoreDisabled = errors.New("session store disabled")

var (
	buildMu sync.Mutex
	// Redis 健康检查与热更新共享状态。
	reloadStopCh chan struct{}
)

// StoreRecord 是外部存储保存的一条 session 绑定记录。
//
// 该记录只作为恢复索引使用，业务 TTL 不作为懒恢复拦截条件；
// scheduler 崩溃后只要外部 key 仍存在且绑定实例可用，就允许按绑定关系懒恢复。正常运行时由 scheduler 内存 timer 主动过期并删除外部 key。
type StoreRecord struct {
	InstanceID      string `json:"instanceID"`
	SchedulerID     string `json:"schedulerID"`
	SessionID       string `json:"sessionID"`
	SessionCtxID    string `json:"sessionCtxID,omitempty"`
	SessionTTL      int    `json:"sessionTTL"`
	Concurrency     int    `json:"concurrency"`
	UpdatedAtUnixNs int64  `json:"updatedAtUnixNs"`
}

// Store 抽象外部 session 绑定存储。
// Redis 与 DataSystem 实现同样的 Save/Get/Delete 语义，恢复路径保持一致，只有底层读写实现不同。
//
// 删除操作不引入 Lua 脚本，也不要求强原子 compare-and-delete；
// 新绑定和懒恢复成功时通过 Save() 覆盖旧值，正常过期时尽力 Delete()。
type Store interface {
	// Save 写入或覆盖一条 session 绑定记录。Redis 后端会刷新物理 TTL。
	Save(sessionKey string, record StoreRecord) error
	// Get 按 session cache key 查询外部记录。miss 时返回 (nil, nil)。
	Get(sessionKey string) (*StoreRecord, error)
	// Delete 删除外部记录。key 不存在不视为错误。
	Delete(sessionKey string) error
	// Backend 返回后端标识，用于日志和指标。
	Backend() string
}

// Config 是构造 Store 所需的参数。所有字段在构造时确定，store 生命周期内不变。
//
// Redis 后端不在此缓存 client 指针：redisStore 每次 op 都调 v6.GetRedisCmd()
// 取全局 client，使得 BuildRedisClient 换全局后所有已存在的 redisStore 在下一次 op
// 立即生效（store 是函数级长期存活对象，必须能感知热更新）。
//
// 物理 key 只保留 session 绑定所必需的三个维度：函数（FuncCacheKey）、集群（Cluster）、
// session（sessionKey）。不再编 instanceType/resKey——它们与路由层重复（路由保证同一
// session 同一时刻只归一个 scheduler），且会阻碍 concurrencyscheduler 与 litescheduler
// 对同一函数的 session 记录共享同一物理 key。
type Config struct {
	// Backend 取值为 BackendRedis / BackendDataSystem。空字符串或未知值会被
	// config 加载期校验拦截；New() 不再接受空字符串作为合法 backend。
	Backend string
	// Cluster 集群隔离字段，避免多环境共享 Redis 时 key 冲突。
	Cluster string
	// FuncCacheKey 即函数级隔离 key（concurrencyscheduler 与 litescheduler 统一传
	// funcSpec.FuncKey），physicalKey 会对其再做一次 SHA256 取 16 hex。
	FuncCacheKey string
	// SchedulerID 写入 record 的 scheduler 标识，用于灰度、owner 和诊断。
	SchedulerID string
	// BackendTTLSeconds 外部存储 key 物理 TTL（恢复窗口），Redis 与 DataSystem 后端共用。
	// 默认 24h（defaultRecoveryWindowSeconds）。业务 session TTL 不参与外部 key 过期（解耦）。
	BackendTTLSeconds int
	// DSOption DataSystem 后端使用的 Option 构造参数。
	DSOption DSOptionConfig
}

// DSOptionConfig 描述 DataSystem 后端构造 Option 所需的字段。
type DSOptionConfig struct {
	TenantID  string
	NodeIP    string
	Cluster   string
	WriteMode api.WriteModeEnum
	TTLSecond uint32
}

// New 根据配置构造 SessionStore。Backend 必须是 redis 或 datasystem，空字符串与
// 未知值均返回错误（"不配置外部存储"的运行模式已废弃，由 config 加载期校验兜底，
// 此处再做一次防御性校验）。
//
// Redis 与 DataSystem 后端的物理 TTL 统一用 defaultRecoveryWindowSeconds（24h）兜底，
// 保证两后端崩溃恢复窗口一致。BackendTTLSeconds 显式配置时两后端都用它。
// Redis 后端不要求构造期 client 已就绪——redisStore 每次 op 调 GetRedisCmd()，未初始化时返回 errStoreDisabled fail-open。
// 启动期 client 就绪由 config.InitSessionStoreRedis（cmd 入口）保证。
func New(cfg Config) (Store, error) {
	switch cfg.Backend {
	case BackendDataSystem:
		if cfg.DSOption.TTLSecond <= 0 {
			cfg.DSOption.TTLSecond = defaultRecoveryWindowSeconds
		}
		return &dataSystemStore{cfg: cfg}, nil
	case BackendRedis:
		ttl := cfg.BackendTTLSeconds
		if ttl <= 0 {
			ttl = defaultRecoveryWindowSeconds
		}
		return &redisStore{cfg: cfg, ttl: time.Duration(ttl) * time.Second}, nil
	default:
		return nil, fmt.Errorf("invalid session store backend: %q, only %q/%q are supported",
			cfg.Backend, BackendRedis, BackendDataSystem)
	}
}

// IsRedisBackend 在 backend=redis 时返回 true，datasystem 时返回 false，
// 其他值（含空字符串）返回 error。由 cmd 入口 InitSessionStoreRedis 调用，
// 决定是否初始化 Redis client。
func IsRedisBackend(backend string) (bool, error) {
	switch backend {
	case BackendDataSystem:
		return false, nil
	case BackendRedis:
		return true, nil
	default:
		return false, fmt.Errorf("invalid session store backend: %q, only %q/%q are supported",
			backend, BackendRedis, BackendDataSystem)
	}
}

// BuildRedisClient 是 Init/Reload 的公共实现：唯一 client 构造点、唯一配置发布点、
// 唯一 checker goroutine 生命周期管理点。
//
// 流程：v6.New 建新 client → close 旧 checkerStopCh（旧 goroutine 退出）→ 建新
// checkerStopCh 并发布 → SetRedisCmd 换全局 → 启新 checker goroutine。顺序保证：
// 旧 checker 在 SetRedisCmd 前已退出、新 checker 在 SetRedisCmd 后才起，无新旧
// checker 同时 Ping 同一/不同 client 的竞态。
//
// 设计：
//   - 重建唯一入口在此处，checker 只 Ping 不重建，故无 stale 比对、无 reconnect
//     闭包、无 atomic 闭包指针。配置刷新天然跟随 Reload——每次调用都用新 cfg New
//     client + 启新 checker。
//   - procStopCh 由外部传入（进程级，永不重建），reloadStopCh 由本函数管理（Reload 级）。
//     两个 stop 通道职责分离：procStopCh 关闭代表进程退出，reloadStopCh 关闭代表
//     被新一次 Reload 取代。
func BuildRedisClient(cfg v6.Config, procStopCh <-chan struct{}) (*v6.Client, error) {
	if cfg.ServerAddr == "" {
		return nil, errors.New("redis serverAddr is empty")
	}
	param := toParam(cfg)
	cli, err := v6.New(param)
	if err != nil {
		return nil, fmt.Errorf("new redis client failed, err: %w", err)
	}
	// 临界区：close 旧 / store 新 / SetRedisCmd / 启新 checker / close 旧 client
	// 五步必须原子，否则两并发调用会双 close 同一 reloadStopCh 触发 panic。
	// v6.New 在锁外，建连耗时不会阻塞其他并发 Reload。
	buildMu.Lock()
	defer buildMu.Unlock()
	if reloadStopCh != nil {
		close(reloadStopCh)
		reloadStopCh = nil // 置 nil，下次进锁跳过 close
	}
	reloadStopCh = make(chan struct{})
	// 3. 换全局 client——旧 checker 已退出、新 checker 还没起，无并发访问。
	//    捕获旧 client，发布新 client 后关闭旧底层连接池，避免 Reload 路径泄漏
	//    连接池（每次配置变更都换新池，旧池永不释放会逐步耗尽 fd/端口）。in-flight
	//    请求持有的旧 client 指针会因 pool 关闭而 op 失败，但 sessionstore op 有
	//    500ms 超时且 fail-open 语义，Reload 稀有，可接受。
	old := v6.GetRedisCmd()
	v6.SetRedisCmd(cli)
	// 4. 启新 checker
	go v6.CheckRedisConnectivity(procStopCh, reloadStopCh)
	if old != nil {
		if err := old.Close(); err != nil {
			log.GetLogger().Warnf("close old redis client on reload failed, err: %s", err.Error())
		}
	}
	return cli, nil
}

// toParam 把 v6.Config 转成 v6.NewRedisClientParam。
func toParam(cfg v6.Config) v6.NewRedisClientParam {
	return v6.NewRedisClientParam{
		ServerMode: cfg.ServerMode,
		ServerAddr: cfg.ServerAddr,
		Password:   cfg.Password,
		Timeout:    cfg.TimeoutConf,
		EnableTLS:  cfg.EnableTLS,
	}
}

// NoopStore 是 MakeStore 在 New() 失败时的 fail-open 兜底实现：所有方法均为 no-op。
// 不对用户配置暴露——backend 必须显式 redis/datasystem，空字符串会在 config 加载期
// 被拦截，不会走到 NoopStore。仅在初始化异常时使用，保证调度主流程不因外部存储
// 初始化失败而中断。
type NoopStore struct{}

// Save -
func (NoopStore) Save(string, StoreRecord) error {
	return nil
}

// Get -
func (NoopStore) Get(string) (*StoreRecord, error) {
	return nil, nil
}

// Delete -
func (NoopStore) Delete(string) error {
	return nil
}

// Backend -
func (NoopStore) Backend() string {
	return BackendNoop
}

// physicalKey 把所有可变成分 SHA256 取 16 hex 拼成物理 key，保证字符集（纯 hex + ':'）
// 满足 DataSystem key 正则 ^[a-zA-Z0-9\-_!@#%\^\*\(\)\+\=\:;]*$，且无 '{}'。
//
// 格式: faasscheduler:session:<funcCacheKeyHash16>:<clusterHash16>:<sessionKeyHash16>
//
// 只保留 session 绑定所必需的三个维度（函数/集群/session），不再编 instanceType：
// instanceType（scaled/reserved/lite）与路由层重复——路由保证同一 session 同一时刻只归
// 一个 scheduler 持有者，去掉后 concurrencyscheduler 与 litescheduler 对同一函数的
// session 会落到同一物理 key，实现跨 scheduler 的 session 记录共享与懒恢复兼容。
//
// 长度上限 = 22("faasscheduler:session:") + 16 + 1 + 16 + 1 + 16 = 72 ≤ 255 ✓
// 16 hex = 64 bit，函数/集群数量小、session 数百万级，碰撞概率可忽略。
//
// Redis 后端不使用 hash tag：本方案仅做单 key GET/SET/DEL，无跨 key 操作，不需要同 slot 归并。
func physicalKey(cfg Config, sessionKey string) string {
	funcHash := sha256.Sum256([]byte(cfg.FuncCacheKey))
	clusterHash := sha256.Sum256([]byte(cfg.Cluster))
	sessionHash := sha256.Sum256([]byte(sessionKey))
	key := fmt.Sprintf("faasscheduler:session:%s:%s:%s",
		hex.EncodeToString(funcHash[:])[:hashMaxLength],
		hex.EncodeToString(clusterHash[:])[:hashMaxLength],
		hex.EncodeToString(sessionHash[:])[:hashMaxLength])
	// DEBUG 日志：记录生成的物理 key 与 hash 前的各字段原值，便于从 Redis/DataSystem 中
	// 看到哈希 key 时反查它对应的函数/集群/session。sessionKey 用 %q 转义（含 \x00 等控制字符）。
	log.GetLogger().Debugf("sessionstore physical key generated, key=%s, "+
		"funcCacheKey=%s, cluster=%s, sessionKey=%q",
		key, cfg.FuncCacheKey, cfg.Cluster, sessionKey)
	return key
}

// fillRecord 用当前时间戳补齐 record 的诊断字段。
func fillRecord(cfg Config, record *StoreRecord) {
	if record.SchedulerID == "" {
		record.SchedulerID = cfg.SchedulerID
	}
	record.UpdatedAtUnixNs = time.Now().UnixNano()
}

type redisStore struct {
	cfg Config
	ttl time.Duration
}

func (s *redisStore) Save(sessionKey string, record StoreRecord) error {
	cli := v6.GetRedisCmd()
	if cli == nil {
		return errStoreDisabled
	}
	if sessionKey == "" {
		return fmt.Errorf("sessionKey is empty")
	}
	fillRecord(s.cfg, &record)
	value, err := json.Marshal(record)
	if err != nil {
		return fmt.Errorf("marshal session record failed: %w", err)
	}
	key := physicalKey(s.cfg, sessionKey)
	if err := cli.Set(key, string(value), s.ttl, redisOpTimeout); err != nil {
		log.GetLogger().Warnf("sessionstore redis SET failed, key=%s, err=%s", key, err.Error())
		return err
	}
	return nil
}

func (s *redisStore) Get(sessionKey string) (*StoreRecord, error) {
	cli := v6.GetRedisCmd()
	if cli == nil {
		return nil, errStoreDisabled
	}
	if sessionKey == "" {
		return nil, fmt.Errorf("sessionKey is empty")
	}
	key := physicalKey(s.cfg, sessionKey)
	value, err := cli.Get(key, redisOpTimeout)
	if err != nil {
		if errors.Is(err, v6.Nil) {
			return nil, nil
		}
		log.GetLogger().Warnf("sessionstore redis GET failed, key=%s, err=%s", key, err.Error())
		return nil, err
	}
	var record StoreRecord
	if err := json.Unmarshal([]byte(value), &record); err != nil {
		log.GetLogger().Warnf("sessionstore redis GET unmarshal failed, key=%s, err=%s", key, err.Error())
		return nil, nil
	}
	return &record, nil
}

func (s *redisStore) Delete(sessionKey string) error {
	cli := v6.GetRedisCmd()
	if cli == nil {
		return errStoreDisabled
	}
	if sessionKey == "" {
		return fmt.Errorf("sessionKey is empty")
	}
	key := physicalKey(s.cfg, sessionKey)
	if err := cli.Delete(key, redisOpTimeout); err != nil {
		log.GetLogger().Warnf("sessionstore redis DEL failed, key=%s, err=%s", key, err.Error())
		return err
	}
	return nil
}

func (s *redisStore) Backend() string {
	return BackendRedis
}

type dataSystemStore struct {
	cfg Config
}

func (s *dataSystemStore) Save(sessionKey string, record StoreRecord) error {
	if sessionKey == "" {
		return fmt.Errorf("sessionKey is empty")
	}
	fillRecord(s.cfg, &record)
	value, err := json.Marshal(record)
	if err != nil {
		return fmt.Errorf("marshal session record failed: %w", err)
	}
	key := physicalKey(s.cfg, sessionKey)
	opt := s.buildOption()
	if err := datasystemclient.KVPutWithRetry(key, value, opt, uuid.New().String()); err != nil {
		log.GetLogger().Warnf("sessionstore datasystem PUT failed, key=%s, err=%s", key, err.Error())
		return err
	}
	return nil
}

func (s *dataSystemStore) Get(sessionKey string) (*StoreRecord, error) {
	if sessionKey == "" {
		return nil, fmt.Errorf("sessionKey is empty")
	}
	key := physicalKey(s.cfg, sessionKey)
	resp, err := datasystemclient.KVGetWithRetry(key, s.buildOption(), uuid.New().String())
	if err != nil {
		log.GetLogger().Warnf("sessionstore datasystem GET failed, key=%s, err=%s", key, err.Error())
		return nil, err
	}
	if len(resp) == 0 {
		return nil, nil
	}
	var record StoreRecord
	if err := json.Unmarshal(resp, &record); err != nil {
		log.GetLogger().Warnf("sessionstore datasystem GET unmarshal failed, key=%s, err=%s", key, err.Error())
		return nil, nil
	}
	return &record, nil
}

func (s *dataSystemStore) Delete(sessionKey string) error {
	if sessionKey == "" {
		return fmt.Errorf("sessionKey is empty")
	}
	key := physicalKey(s.cfg, sessionKey)
	if err := datasystemclient.KVDelWithRetry(key, s.buildOption(), uuid.New().String()); err != nil {
		log.GetLogger().Warnf("sessionstore datasystem DEL failed, key=%s, err=%s", key, err.Error())
		return err
	}
	return nil
}

func (s *dataSystemStore) Backend() string {
	return BackendDataSystem
}

func (s *dataSystemStore) buildOption() *datasystemclient.Option {
	return &datasystemclient.Option{
		TenantID:  s.cfg.DSOption.TenantID,
		NodeIP:    s.cfg.DSOption.NodeIP,
		Cluster:   s.cfg.DSOption.Cluster,
		WriteMode: s.cfg.DSOption.WriteMode,
		TTLSecond: s.cfg.DSOption.TTLSecond,
	}
}
