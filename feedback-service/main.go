package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

type app struct {
	db                *sql.DB
	siteDir           string
	trustProxyHeaders bool
	codeStore         *codeStore
	ipLimiter         *memoryLimiter
	deviceLimiter     *memoryLimiter
}

type codeStore struct {
	mu          sync.RWMutex
	codes       map[string]struct{}
	signalDates map[string]map[string]struct{}
	siteDir     string
	lastLoad    time.Time
	lastCheck   time.Time
}

type memoryLimiter struct {
	mu      sync.Mutex
	entries map[string][]time.Time
	window  time.Duration
	limit   int
}

type publicResults struct {
	Stocks []publicStock `json:"stocks"`
}

type publicStock struct {
	Code         string        `json:"code"`
	LatestSignal *publicSignal `json:"latest_signal"`
}

type publicSignal struct {
	Date string `json:"date"`
}

type summaryItem struct {
	Code       string  `json:"code"`
	SignalDate string  `json:"signal_date"`
	UpCount    int     `json:"up_count"`
	DownCount  int     `json:"down_count"`
	Score      int     `json:"score"`
	MyVote     *string `json:"my_vote,omitempty"`
}

type voteRequest struct {
	Code       string `json:"code"`
	SignalDate string `json:"signal_date"`
	Action     string `json:"action"`
	DeviceID   string `json:"device_id"`
}

type signalRef struct {
	Code       string `json:"code"`
	SignalDate string `json:"signal_date"`
}

type summaryRequest struct {
	Codes   []string    `json:"codes"`
	Signals []signalRef `json:"signals"`
}

var (
	codePattern   = regexp.MustCompile(`^\d{6}$`)
	devicePattern = regexp.MustCompile(`^[a-zA-Z0-9-]{8,64}$`)
)

func main() {
	port := getenv("PORT", "8081")
	dbPath := getenv("DB_PATH", "./feedback.db")
	siteDir := getenv("SITE_DIR", "../dist/publish")
	trustProxyHeaders := os.Getenv("TRUST_PROXY_HEADERS") == "1"

	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		log.Fatalf("open db: %v", err)
	}
	defer db.Close()

	if err := initDB(db); err != nil {
		log.Fatalf("init db: %v", err)
	}

	application := &app{
		db:                db,
		siteDir:           siteDir,
		trustProxyHeaders: trustProxyHeaders,
		codeStore: &codeStore{
			codes:       make(map[string]struct{}),
			signalDates: make(map[string]map[string]struct{}),
			siteDir:     siteDir,
		},
		ipLimiter:     newMemoryLimiter(20, time.Minute),
		deviceLimiter: newMemoryLimiter(8, time.Minute),
	}

	if err := application.codeStore.reload(); err != nil {
		log.Printf("initial code load failed: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", application.handleHealth)
	mux.HandleFunc("/api/feedback/summary", application.handleSummary)
	mux.HandleFunc("/api/feedback/vote", application.handleVote)

	server := &http.Server{
		Addr:              "127.0.0.1:" + port,
		Handler:           withJSON(withCORS(mux)),
		ReadHeaderTimeout: 5 * time.Second,
	}

	log.Printf("feedback-service listening on %s", server.Addr)
	log.Fatal(server.ListenAndServe())
}

func initDB(db *sql.DB) error {
	stmts := []string{
		`CREATE TABLE IF NOT EXISTS stock_feedback_votes (
			code TEXT NOT NULL,
			signal_date TEXT NOT NULL,
			device_id TEXT NOT NULL,
			vote TEXT NOT NULL,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY (code, signal_date, device_id)
		);`,
		`CREATE TABLE IF NOT EXISTS stock_feedback_summary (
			code TEXT NOT NULL,
			signal_date TEXT NOT NULL,
			up_count INTEGER NOT NULL DEFAULT 0,
			down_count INTEGER NOT NULL DEFAULT 0,
			score INTEGER NOT NULL DEFAULT 0,
			updated_at TEXT NOT NULL,
			PRIMARY KEY (code, signal_date)
		);`,
	}
	for _, stmt := range stmts {
		if _, err := db.Exec(stmt); err != nil {
			return err
		}
	}
	return migrateLegacyTables(db)
}

func (a *app) handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (a *app) handleSummary(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	if err := a.codeStore.ensureFresh(); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to load published codes")
		return
	}

	var req summaryRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json body")
		return
	}

	signals := normalizeSignalRefs(req.Signals)
	if len(signals) == 0 {
		signals = a.codeStore.signalRefsForCodes(req.Codes)
	}
	if len(signals) == 0 {
		writeJSON(w, http.StatusOK, map[string]any{"items": []summaryItem{}})
		return
	}
	for _, signal := range signals {
		if !a.codeStore.hasSignal(signal.Code, signal.SignalDate) {
			writeError(w, http.StatusBadRequest, "unknown code")
			return
		}
	}

	items, err := a.fetchSummary(r.Context(), signals)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to load summary")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items})
}

func (a *app) handleVote(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	if err := a.codeStore.ensureFresh(); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to load published codes")
		return
	}

	ip := a.clientIP(r)
	if !a.ipLimiter.Allow(ip) {
		writeError(w, http.StatusTooManyRequests, "too many requests from this IP")
		return
	}

	var req voteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json body")
		return
	}

	if !codePattern.MatchString(req.Code) {
		writeError(w, http.StatusBadRequest, "invalid code")
		return
	}
	req.SignalDate = strings.TrimSpace(req.SignalDate)
	if req.SignalDate == "" {
		writeError(w, http.StatusBadRequest, "invalid signal_date")
		return
	}
	if !devicePattern.MatchString(req.DeviceID) {
		writeError(w, http.StatusBadRequest, "invalid device_id")
		return
	}
	if !a.deviceLimiter.Allow(req.DeviceID) {
		writeError(w, http.StatusTooManyRequests, "too many requests from this device")
		return
	}
	if !a.codeStore.hasSignal(req.Code, req.SignalDate) {
		writeError(w, http.StatusBadRequest, "unknown code")
		return
	}

	switch req.Action {
	case "up", "down", "clear":
	default:
		writeError(w, http.StatusBadRequest, "invalid action")
		return
	}

	item, err := a.applyVote(r.Context(), req)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save vote")
		return
	}
	writeJSON(w, http.StatusOK, item)
}

func (a *app) fetchSummary(ctx context.Context, signals []signalRef) ([]summaryItem, error) {
	items := make([]summaryItem, 0, len(signals))
	for _, signal := range signals {
		item := summaryItem{Code: signal.Code, SignalDate: signal.SignalDate}
		row := a.db.QueryRowContext(
			ctx,
			`SELECT up_count, down_count, score FROM stock_feedback_summary WHERE code = ? AND signal_date = ?`,
			signal.Code,
			signal.SignalDate,
		)
		switch err := row.Scan(&item.UpCount, &item.DownCount, &item.Score); {
		case err == nil:
		case errors.Is(err, sql.ErrNoRows):
		default:
			return nil, err
		}
		items = append(items, item)
	}
	return items, nil
}

func (a *app) applyVote(ctx context.Context, req voteRequest) (summaryItem, error) {
	tx, err := a.db.BeginTx(ctx, nil)
	if err != nil {
		return summaryItem{}, err
	}
	defer tx.Rollback()

	var oldVote string
	err = tx.QueryRowContext(
		ctx,
		`SELECT vote FROM stock_feedback_votes WHERE code = ? AND signal_date = ? AND device_id = ?`,
		req.Code,
		req.SignalDate,
		req.DeviceID,
	).Scan(&oldVote)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return summaryItem{}, err
	}
	if errors.Is(err, sql.ErrNoRows) {
		oldVote = ""
	}

	now := time.Now().Format(time.RFC3339)
	if req.Action == "clear" {
		if _, err := tx.ExecContext(
			ctx,
			`DELETE FROM stock_feedback_votes WHERE code = ? AND signal_date = ? AND device_id = ?`,
			req.Code,
			req.SignalDate,
			req.DeviceID,
		); err != nil {
			return summaryItem{}, err
		}
	} else {
		if _, err := tx.ExecContext(
			ctx,
			`INSERT INTO stock_feedback_votes(code, signal_date, device_id, vote, created_at, updated_at)
			 VALUES(?, ?, ?, ?, ?, ?)
			 ON CONFLICT(code, signal_date, device_id)
			 DO UPDATE SET vote = excluded.vote, updated_at = excluded.updated_at`,
			req.Code,
			req.SignalDate,
			req.DeviceID,
			req.Action,
			now,
			now,
		); err != nil {
			return summaryItem{}, err
		}
	}

	upCount, downCount, score := applyCounts(oldVote, req.Action)
	var currentUp, currentDown int
	row := tx.QueryRowContext(
		ctx,
		`SELECT up_count, down_count FROM stock_feedback_summary WHERE code = ? AND signal_date = ?`,
		req.Code,
		req.SignalDate,
	)
	switch err := row.Scan(&currentUp, &currentDown); {
	case err == nil:
		upCount += currentUp
		downCount += currentDown
	case errors.Is(err, sql.ErrNoRows):
	default:
		return summaryItem{}, err
	}

	score += currentUp - currentDown
	if upCount < 0 {
		upCount = 0
	}
	if downCount < 0 {
		downCount = 0
	}
	score = upCount - downCount

	if _, err := tx.ExecContext(
		ctx,
		`INSERT INTO stock_feedback_summary(code, signal_date, up_count, down_count, score, updated_at)
		 VALUES(?, ?, ?, ?, ?, ?)
		 ON CONFLICT(code, signal_date)
		 DO UPDATE SET up_count = excluded.up_count, down_count = excluded.down_count, score = excluded.score, updated_at = excluded.updated_at`,
		req.Code,
		req.SignalDate,
		upCount,
		downCount,
		score,
		now,
	); err != nil {
		return summaryItem{}, err
	}

	if err := tx.Commit(); err != nil {
		return summaryItem{}, err
	}

	var myVote *string
	if req.Action != "clear" {
		myVote = &req.Action
	}
	return summaryItem{
		Code:       req.Code,
		SignalDate: req.SignalDate,
		UpCount:    upCount,
		DownCount:  downCount,
		Score:      score,
		MyVote:     myVote,
	}, nil
}

func applyCounts(oldVote, action string) (upDelta, downDelta, scoreDelta int) {
	switch oldVote {
	case "up":
		upDelta--
	case "down":
		downDelta--
	}
	switch action {
	case "up":
		upDelta++
	case "down":
		downDelta++
	}
	scoreDelta = upDelta - downDelta
	return upDelta, downDelta, scoreDelta
}

func (c *codeStore) ensureFresh() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if time.Since(c.lastCheck) < 10*time.Second {
		return nil
	}
	c.lastCheck = time.Now()
	return c.reloadLocked()
}

func (c *codeStore) reload() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.reloadLocked()
}

func (c *codeStore) reloadLocked() error {
	paths := []string{
		filepath.Join(c.siteDir, "buy_scan_results.json"),
		filepath.Join(c.siteDir, "sell_scan_results.json"),
	}
	updated := make(map[string]struct{})
	signalDates := make(map[string]map[string]struct{})
	for _, path := range paths {
		data, err := os.ReadFile(path)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return err
		}
		var payload publicResults
		if err := json.Unmarshal(data, &payload); err != nil {
			return err
		}
		for _, stock := range payload.Stocks {
			if codePattern.MatchString(stock.Code) {
				updated[stock.Code] = struct{}{}
				if stock.LatestSignal != nil {
					signalDate := strings.TrimSpace(stock.LatestSignal.Date)
					if signalDate != "" {
						if signalDates[stock.Code] == nil {
							signalDates[stock.Code] = make(map[string]struct{})
						}
						signalDates[stock.Code][signalDate] = struct{}{}
					}
				}
			}
		}
	}
	c.codes = updated
	c.signalDates = signalDates
	c.lastLoad = time.Now()
	return nil
}

func (c *codeStore) has(code string) bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	_, ok := c.codes[code]
	return ok
}

func (c *codeStore) hasSignal(code, signalDate string) bool {
	c.mu.RLock()
	defer c.mu.RUnlock()

	dates := c.signalDates[code]
	if len(dates) == 0 {
		return false
	}
	_, ok := dates[signalDate]
	return ok
}

func (c *codeStore) signalRefsForCodes(codes []string) []signalRef {
	c.mu.RLock()
	defer c.mu.RUnlock()

	normalized := normalizeCodes(codes)
	signals := make([]signalRef, 0, len(normalized))
	for _, code := range normalized {
		for signalDate := range c.signalDates[code] {
			signals = append(signals, signalRef{
				Code:       code,
				SignalDate: signalDate,
			})
		}
	}
	return signals
}

func newMemoryLimiter(limit int, window time.Duration) *memoryLimiter {
	return &memoryLimiter{
		entries: make(map[string][]time.Time),
		window:  window,
		limit:   limit,
	}
}

func (l *memoryLimiter) Allow(key string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()

	now := time.Now()
	recent := make([]time.Time, 0, len(l.entries[key])+1)
	for _, ts := range l.entries[key] {
		if now.Sub(ts) < l.window {
			recent = append(recent, ts)
		}
	}
	if len(recent) >= l.limit {
		l.entries[key] = recent
		return false
	}
	l.entries[key] = append(recent, now)
	return true
}

func splitCodes(raw string) []string {
	if raw == "" {
		return nil
	}
	return normalizeCodes(strings.Split(raw, ","))
}

func normalizeCodes(codes []string) []string {
	if len(codes) == 0 {
		return nil
	}
	out := make([]string, 0, len(codes))
	seen := make(map[string]struct{})
	for _, raw := range codes {
		code := strings.TrimSpace(raw)
		if !codePattern.MatchString(code) {
			continue
		}
		if _, ok := seen[code]; ok {
			continue
		}
		seen[code] = struct{}{}
		out = append(out, code)
	}
	return out
}

func normalizeSignalRefs(signals []signalRef) []signalRef {
	if len(signals) == 0 {
		return nil
	}
	out := make([]signalRef, 0, len(signals))
	seen := make(map[string]struct{})
	for _, raw := range signals {
		code := strings.TrimSpace(raw.Code)
		signalDate := strings.TrimSpace(raw.SignalDate)
		if !codePattern.MatchString(code) || signalDate == "" {
			continue
		}
		key := code + "\x00" + signalDate
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		out = append(out, signalRef{
			Code:       code,
			SignalDate: signalDate,
		})
	}
	return out
}

func migrateLegacyTables(db *sql.DB) error {
	if err := migrateTableIfNeeded(
		db,
		"stock_feedback_votes",
		[]string{"code", "signal_date", "device_id", "vote", "created_at", "updated_at"},
		[]string{
			`ALTER TABLE stock_feedback_votes RENAME TO stock_feedback_votes_legacy;`,
			`CREATE TABLE stock_feedback_votes (
				code TEXT NOT NULL,
				signal_date TEXT NOT NULL,
				device_id TEXT NOT NULL,
				vote TEXT NOT NULL,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL,
				PRIMARY KEY (code, signal_date, device_id)
			);`,
			`INSERT INTO stock_feedback_votes(code, signal_date, device_id, vote, created_at, updated_at)
			 SELECT code, '', device_id, vote, created_at, updated_at FROM stock_feedback_votes_legacy;`,
			`DROP TABLE stock_feedback_votes_legacy;`,
		},
	); err != nil {
		return err
	}

	return migrateTableIfNeeded(
		db,
		"stock_feedback_summary",
		[]string{"code", "signal_date", "up_count", "down_count", "score", "updated_at"},
		[]string{
			`ALTER TABLE stock_feedback_summary RENAME TO stock_feedback_summary_legacy;`,
			`CREATE TABLE stock_feedback_summary (
				code TEXT NOT NULL,
				signal_date TEXT NOT NULL,
				up_count INTEGER NOT NULL DEFAULT 0,
				down_count INTEGER NOT NULL DEFAULT 0,
				score INTEGER NOT NULL DEFAULT 0,
				updated_at TEXT NOT NULL,
				PRIMARY KEY (code, signal_date)
			);`,
			`INSERT INTO stock_feedback_summary(code, signal_date, up_count, down_count, score, updated_at)
			 SELECT code, '', up_count, down_count, score, updated_at FROM stock_feedback_summary_legacy;`,
			`DROP TABLE stock_feedback_summary_legacy;`,
		},
	)
}

func migrateTableIfNeeded(db *sql.DB, table string, requiredColumns []string, migration []string) error {
	columns, err := tableColumns(db, table)
	if err != nil {
		return err
	}
	if hasAllColumns(columns, requiredColumns) {
		return nil
	}
	for _, stmt := range migration {
		if _, err := db.Exec(stmt); err != nil {
			return err
		}
	}
	return nil
}

func tableColumns(db *sql.DB, table string) (map[string]struct{}, error) {
	rows, err := db.Query(`PRAGMA table_info(` + table + `)`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	columns := make(map[string]struct{})
	for rows.Next() {
		var cid int
		var name string
		var dataType string
		var notNull int
		var defaultValue any
		var pk int
		if err := rows.Scan(&cid, &name, &dataType, &notNull, &defaultValue, &pk); err != nil {
			return nil, err
		}
		columns[name] = struct{}{}
	}
	return columns, rows.Err()
}

func hasAllColumns(columns map[string]struct{}, required []string) bool {
	for _, column := range required {
		if _, ok := columns[column]; !ok {
			return false
		}
	}
	return true
}

func (a *app) clientIP(r *http.Request) string {
	if a.trustProxyHeaders {
		forwarded := r.Header.Get("X-Forwarded-For")
		if forwarded != "" {
			return strings.TrimSpace(strings.Split(forwarded, ",")[0])
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func withCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func withJSON(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		next.ServeHTTP(w, r)
	})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}

func getenv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
