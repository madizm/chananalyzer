# Public Deployment

## One-Click Publish

日常更新优先使用一键脚本：

```bash
REMOTE_HOST=117.50.199.81 \
REMOTE_USER=root \
REMOTE_BASE_DIR=/srv/chananalyzer \
bash scripts/publish_public_site.sh --limit 100 --goarch amd64
```

这个脚本会顺序执行：

1. 导出公网结果 JSON 到 `dist/publish/`
2. 构建静态站点到 `dist/site/`
3. 构建 Linux feedback 二进制到 `dist/release/`
4. 通过 `rsync` 同步到服务器

常用参数：

```bash
--limit 100
--goarch amd64
--version 2026.03.22
--install-service-files
--skip-feedback-build
```

示例：

首次部署时顺便上传 `nginx` / `systemd` 样板文件：

```bash
REMOTE_HOST=117.50.199.81 \
REMOTE_USER=root \
REMOTE_BASE_DIR=/srv/chananalyzer \
bash scripts/publish_public_site.sh --limit 100 --goarch amd64 --install-service-files
```

如果只是更新扫描结果和前端，不重新构建 feedback 服务：

```bash
REMOTE_HOST=117.50.199.81 \
bash scripts/publish_public_site.sh --limit 100 --skip-feedback-build
```

## Split Commands

如果你要拆开执行，仍然可以按下面三步：

### 1. 导出结果 JSON

```bash
python scripts/export_public_results.py --output-dir dist/publish --limit 100 --version 1
```

### 2. 构建静态站点和 feedback 二进制

Linux `amd64`:

```bash
python scripts/build_public_release.py --goos linux --goarch amd64
```

Linux `arm64`:

```bash
python scripts/build_public_release.py --goos linux --goarch arm64
```

### 3. 同步到服务器

```bash
REMOTE_HOST=117.50.199.81 \
REMOTE_USER=root \
REMOTE_BASE_DIR=/srv/chananalyzer \
FEEDBACK_BINARY_NAME=feedback-service-linux-amd64 \
bash scripts/deploy_public_release.sh
```

## Output Layout

构建完成后产物如下：

- `dist/publish/`
  - `buy_scan_results.json`
  - `sell_scan_results.json`
  - `manifest.json`
- `dist/site/`
  - 独立静态站点和最终发布 JSON
- `dist/release/`
  - `feedback-service-linux-amd64` 或其他目标架构二进制

## Server Layout

服务器侧默认目录：

- `/srv/chananalyzer/site`
- `/srv/chananalyzer/feedback/feedback-service`
- `/srv/chananalyzer/feedback/feedback.db`

如果需要首次启用服务：

- 检查 `/etc/nginx/conf.d/chanalyzer-public.conf`
- 检查 `/etc/systemd/system/feedback-service.service`
- 执行 `nginx -t`
- 执行 `systemctl daemon-reload`
- 执行 `systemctl enable --now feedback-service nginx`
