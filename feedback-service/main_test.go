package main

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	_ "modernc.org/sqlite"
)

func newTestApp(t *testing.T) *app {
	t.Helper()

	tempDir := t.TempDir()
	siteDir := filepath.Join(tempDir, "site")
	if err := os.MkdirAll(siteDir, 0o755); err != nil {
		t.Fatalf("mkdir site dir: %v", err)
	}

	writeFile := func(name, content string) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(siteDir, name), []byte(content), 0o644); err != nil {
			t.Fatalf("write %s: %v", name, err)
		}
	}

	writeFile("buy_scan_results.json", `{"stocks":[{"code":"000001"},{"code":"600519"}]}`)
	writeFile("sell_scan_results.json", `{"stocks":[{"code":"000858"}]}`)

	db, err := sql.Open("sqlite", filepath.Join(tempDir, "feedback.db"))
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })

	if err := initDB(db); err != nil {
		t.Fatalf("init db: %v", err)
	}

	app := &app{
		db:      db,
		siteDir: siteDir,
		codeStore: &codeStore{
			codes:   make(map[string]struct{}),
			siteDir: siteDir,
		},
		ipLimiter:     newMemoryLimiter(20, 0),
		deviceLimiter: newMemoryLimiter(20, 0),
	}

	if err := app.codeStore.reload(); err != nil {
		t.Fatalf("load codes: %v", err)
	}

	return app
}

func TestVoteFlowAndSummary(t *testing.T) {
	app := newTestApp(t)

	voteReq := httptest.NewRequest(http.MethodPost, "/api/feedback/vote", strings.NewReader(`{"code":"000001","action":"up","device_id":"device-12345678"}`))
	voteReq.Header.Set("Content-Type", "application/json")
	voteRes := httptest.NewRecorder()
	app.handleVote(voteRes, voteReq)

	if voteRes.Code != http.StatusOK {
		t.Fatalf("unexpected vote status: %d body=%s", voteRes.Code, voteRes.Body.String())
	}

	var voted summaryItem
	if err := json.Unmarshal(voteRes.Body.Bytes(), &voted); err != nil {
		t.Fatalf("decode vote response: %v", err)
	}
	if voted.UpCount != 1 || voted.DownCount != 0 || voted.Score != 1 {
		t.Fatalf("unexpected vote counts: %+v", voted)
	}
	if voted.MyVote == nil || *voted.MyVote != "up" {
		t.Fatalf("unexpected my_vote: %+v", voted.MyVote)
	}

	summaryReq := httptest.NewRequest(http.MethodGet, "/api/feedback/summary?codes=000001,600519&device_id=device-12345678", nil)
	summaryRes := httptest.NewRecorder()
	app.handleSummary(summaryRes, summaryReq)

	if summaryRes.Code != http.StatusOK {
		t.Fatalf("unexpected summary status: %d body=%s", summaryRes.Code, summaryRes.Body.String())
	}

	var summary struct {
		Items []summaryItem `json:"items"`
	}
	if err := json.Unmarshal(summaryRes.Body.Bytes(), &summary); err != nil {
		t.Fatalf("decode summary response: %v", err)
	}
	if len(summary.Items) != 2 {
		t.Fatalf("unexpected summary length: %d", len(summary.Items))
	}
	if summary.Items[0].Code != "000001" || summary.Items[0].UpCount != 1 {
		t.Fatalf("unexpected first summary item: %+v", summary.Items[0])
	}
	if summary.Items[0].MyVote == nil || *summary.Items[0].MyVote != "up" {
		t.Fatalf("unexpected first my_vote: %+v", summary.Items[0].MyVote)
	}
	if summary.Items[1].Code != "600519" || summary.Items[1].UpCount != 0 {
		t.Fatalf("unexpected second summary item: %+v", summary.Items[1])
	}
}

func TestVoteRejectsUnknownCode(t *testing.T) {
	app := newTestApp(t)

	req := httptest.NewRequest(http.MethodPost, "/api/feedback/vote", strings.NewReader(`{"code":"123456","action":"up","device_id":"device-12345678"}`))
	req.Header.Set("Content-Type", "application/json")
	res := httptest.NewRecorder()
	app.handleVote(res, req)

	if res.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d body=%s", res.Code, res.Body.String())
	}
}
